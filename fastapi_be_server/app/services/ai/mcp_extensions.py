"""Dot expansion: frozen previews and component-only, one-use approvals."""
import hashlib
import json
import re
import secrets
import time
from datetime import datetime
from mcp.types import CallToolResult, TextContent, ImageContent
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from app.rdb import likenovel_db_session
from app.services.ai import mcp_store as store
from app.services.ai.mcp_config import load as load_config
from app.services.ai import mcp_ai_reader as readers, mcp_member_mail as mail, mcp_promotion as promotion

READ_OPERATIONS = "likenovel.mcp.operations.read"
EXTRA_SCOPES = [READ_OPERATIONS, readers.READ_AI, readers.WRITE_AI, mail.READ_MEMBERS,
                mail.WRITE_MAIL, promotion.CAMPAIGN_SCOPE, promotion.PAID_APPROVAL_SCOPE,
                promotion.BANNER_SCOPE, promotion.PAID_CONVERSION_SCOPE]
UI_URI = "ui://likenovel/operation-approval.html"
ACTIONS = {
    "ai-reader": (readers.WRITE_AI, "ai_reader_writes_enabled"),
    "member-mail": (mail.WRITE_MAIL, "member_mail_enabled"),
    "paid-approval": (promotion.PAID_APPROVAL_SCOPE, "paid_conversion_writes_enabled"),
    "paid-conversion": (promotion.PAID_CONVERSION_SCOPE, "paid_conversion_writes_enabled"),
    "hundred-free": (promotion.CAMPAIGN_SCOPE, "promotion_writes_enabled"),
    "banner": (promotion.BANNER_SCOPE, "banner_writes_enabled"),
}


class ChatGPTFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    download_url: str
    file_id: str
    mime_type: str | None = None
    file_name: str | None = None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode()).hexdigest()


def approval(owner, kind, plan_id, summary, previews=None):
    if kind not in ACTIONS:
        raise ValueError("Unknown expansion action")
    key = "extension-approval:" + secrets.token_hex(16)
    nonce = secrets.token_urlsafe(32)
    frozen = {"kind": kind, "plan_id": plan_id, "summary": summary}
    store.save(key, owner, "pending", {**frozen, "hash": digest(frozen),
        "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(), "expires_at": time.time()+900})
    result_id = ({"ai-reader": "ai-reader-apply:" + plan_id.split(":")[-1],
                  "member-mail": plan_id, "banner": "banner-publish:" + plan_id}.get(kind)
                 or "promotion-apply:" + plan_id)
    display = {**summary, "operation": kind, "result_receipt_id": result_id}
    public = {**display, "approval_id": key, "execution_requires_user_approval": True,
              "approval_expires_in_seconds": 900}
    # MCP _meta is delivered only to the component, never model content.
    content=[TextContent(type="text", text=json.dumps(public, ensure_ascii=False))]
    for preview in previews or []:
        content.append(ImageContent(type="image", data=preview.split(",",1)[1], mimeType="image/webp"))
    return CallToolResult(content=content,
        structuredContent=public, _meta={"images": previews or [], "approval": {"id": key, "nonce": nonce},
                                      "summary": display})


def consume_approval(owner, approval_id, nonce):
    if not re.fullmatch(r"extension-approval:[a-f0-9]{32}", approval_id):
        raise PermissionError("Invalid approval")
    row = store.get(approval_id, owner)
    if not row or row["status"] != "pending" or row["expires_at"] <= time.time():
        raise PermissionError("Approval expired, missing or already used")
    if not isinstance(nonce, str) or not secrets.compare_digest(row["nonce_hash"], hashlib.sha256(nonce.encode()).hexdigest()):
        raise PermissionError("The component's user approval is required")
    frozen = {k: row[k] for k in ("kind", "plan_id", "summary")}
    if row["hash"] != digest(frozen):
        raise PermissionError("Approved plan changed")
    return row


def register(mcp, identity):
    from mcp.types import ToolAnnotations
    def require(scope):
        admin = identity()
        if scope not in admin.scopes:
            raise PermissionError("Reconnect this app to authorize its separate expansion scope")
        return admin
    def tool(name, scope=READ_OPERATIONS, ui=False, private=False, files=None):
        meta = {"securitySchemes": [{"type": "oauth2", "scopes": [scope]}]}
        if ui:
            meta.update({"ui": {"resourceUri": UI_URI}, "openai/outputTemplate": UI_URI})
        if private:
            meta["securitySchemes"][0]["scopes"] = [READ_OPERATIONS, *sorted({value[0] for value in ACTIONS.values()})]
            meta.update({"ui": {"visibility": ["app"]}, "openai/visibility": "private",
                         "openai/widgetAccessible": True})
        if files:
            meta["openai/fileParams"] = files
        return mcp.tool(name=name, structured_output=False, meta=meta,
            annotations=ToolAnnotations(readOnlyHint=not private, destructiveHint=private,
                                        idempotentHint=not private, openWorldHint=private))

    def recent_receipts(owner):
        with store.connection() as db:
            rows=db.execute("SELECT job_id,status,updated FROM receipts WHERE owner=? AND (job_id LIKE 'ai-reader-apply:%' OR job_id LIKE 'promotion-apply:%' OR job_id LIKE 'banner-publish:%' OR (job_id LIKE 'mail:campaign:%' AND status NOT IN ('prepared','used'))) ORDER BY updated DESC LIMIT 20",(owner,)).fetchall()
        return [{"receipt_id":r[0],"status":r[1],"updated_at":r[2]} for r in rows]

    @tool("likenovel_expansion_status")
    async def expansion_status() -> dict:
        admin = require(READ_OPERATIONS)
        config = load_config()
        return {"registered": True, "timezone": "Asia/Seoul",
            "actual_execution": "Only the user's approval button executes the exact frozen plan",
            "receipts": recent_receipts(admin.subject),
            "capabilities": {kind: {"write_enabled": config.get(flag) is True,
                "scope_granted": scope in admin.scopes} for kind, (scope, flag) in ACTIONS.items()},
            "banner_creation": "Generate images in Dot, then pass generated files to banner preparation",
            "proposal_policy": "Actively propose images and placement; exclude works proposed within 7 days; random among remaining eligible works"}

    @tool("likenovel_ai_reader_status", readers.READ_AI)
    async def ai_reader_status(starts_on: str | None=None, page: int=1) -> dict:
        require(readers.READ_AI)
        return await readers.status(starts_on, page)

    @tool("likenovel_prepare_ai_readers", readers.READ_AI, ui=True)
    async def prepare_ai_readers(count: int, starts_on: str, duration_days: int,
                                 mode: str="resume", email_prefix: str | None=None) -> CallToolResult:
        """Prepare exact count/start/duration; creates an approval card, never starts readers."""
        admin=require(readers.READ_AI)
        result=await readers.plan(admin.subject,count,starts_on,duration_days,mode,email_prefix)
        return approval(admin.subject,"ai-reader",result["plan_id"],result)

    @tool("likenovel_member_preview", mail.READ_MEMBERS)
    async def member_preview(filters: dict) -> dict:
        """Preview exact eligible members, masked addresses, latest marketing consent; never sends."""
        admin=require(mail.READ_MEMBERS)
        async with likenovel_db_session() as db:
            return await mail.preview_members(admin.subject,db,filters)

    @tool("likenovel_prepare_member_mail", mail.READ_MEMBERS, ui=True)
    async def prepare_member_mail(preview_id: str, subject: str, body: str) -> CallToolResult:
        """Draft from admin@likenovel.net, recipients BCC; prepare exact text for user's approval."""
        admin=require(mail.READ_MEMBERS)
        result=mail.prepare_campaign(admin.subject,preview_id,subject,body)
        result.update({"subject": subject, "body": body, "sender": "admin@likenovel.net"})
        return approval(admin.subject,"member-mail",result["receipt_id"],result)

    @tool("likenovel_paid_applications")
    async def paid_applications() -> dict:
        """Read pending/accepted paid conversion applications for proactive proposals."""
        require(READ_OPERATIONS)
        async with likenovel_db_session() as db:
            rows=await db.execute(text("SELECT a.id AS apply_id,a.product_id,a.status_code,p.title,p.price_type,p.contract_yn FROM tb_product_paid_apply a JOIN tb_product p ON p.product_id=a.product_id WHERE a.use_yn='Y' AND a.status_code IN ('review','accepted') ORDER BY a.id DESC LIMIT 100"))
            return {"items": [dict(x) for x in rows.mappings().all()]}

    @tool("likenovel_prepare_paid_approval", ui=True)
    async def prepare_paid_approval(apply_id: int) -> CallToolResult:
        admin=require(READ_OPERATIONS)
        async with likenovel_db_session() as db:
            before=await promotion._paid_snapshot(apply_id,db)
        result=promotion.prepare_paid_approval(admin.subject,before,{"role":"admin","user_id":admin.admin_user_id})
        return approval(admin.subject,"paid-approval",result["plan_id"],result)

    @tool("likenovel_prepare_paid_conversion", ui=True)
    async def prepare_paid_conversion(apply_id: int, paid_episode_no: int) -> CallToolResult:
        admin=require(READ_OPERATIONS)
        async with likenovel_db_session() as db:
            before=await promotion.paid_conversion_snapshot(apply_id,db)
        result=promotion.prepare_paid_conversion(admin.subject,before,{"role":"admin","user_id":admin.admin_user_id},paid_episode_no)
        return approval(admin.subject,"paid-conversion",result["plan_id"],result)

    @tool("likenovel_promotion_snapshot")
    async def promotion_snapshot(product_id: int) -> dict:
        require(READ_OPERATIONS)
        if type(product_id) is not int or product_id <= 0:
            raise ValueError("Positive product_id required")
        async with likenovel_db_session() as db:
            return await promotion.campaign_snapshot(product_id,db)

    @tool("likenovel_cp_connection")
    async def cp_connection() -> dict:
        """Connect the real LikeNovel partner CP login once; admin identity is never impersonated."""
        from app.services.ai import mcp_cp_auth as cp
        admin=require(READ_OPERATIONS)
        current=await cp.connection_status(admin.subject)
        return current if current.get("connected") else cp.begin_connection(admin.subject)

    @tool("likenovel_prepare_hundred_free", ui=True)
    async def prepare_hundred_free(product_id: int, ends_at: str) -> CallToolResult:
        """Prepare paid work's episodes 1-100 free until timezone-qualified ends_at; user approves exact plan."""
        from app.services.ai import mcp_cp_auth as cp
        admin=require(READ_OPERATIONS)
        actor=await cp.get_actor(admin.subject)
        async with likenovel_db_session() as db:
            before=await promotion.campaign_snapshot(product_id,db)
        result=promotion.prepare_hundred_free(admin.subject,before,actor,datetime.fromisoformat(ends_at))
        return approval(admin.subject,"hundred-free",result["plan_id"],result)

    @tool("likenovel_banner_brief")
    async def banner_brief(position: str, product_title: str, offer: str, link: str,
                           division: str | None=None, width: int | None=None,
                           height: int | None=None) -> dict:
        """Propose actual banner images, copy, desktop/mobile pixel sizes and placement. Generate images using Dot image tools."""
        from app.services.ai import mcp_banner as banner
        require(READ_OPERATIONS)
        return banner.banner_brief(position,division,product_title=product_title,offer=offer,
                                   link=link,width=width,height=height)

    @tool("likenovel_prepare_banner", ui=True, files=["file","mobile_file"])
    async def prepare_banner(request: dict, file: ChatGPTFile, mobile_file: ChatGPTFile | None=None,
                              width: int | None=None, height: int | None=None) -> CallToolResult:
        """Accept Dot-generated banner files; verify pixels and freeze position/order/link/period. Never publishes without user approval."""
        from app.services.ai import mcp_banner as banner
        admin=require(READ_OPERATIONS)
        async with likenovel_db_session() as db:
            result=await banner.prepare_asset(admin.subject,request,file.model_dump(exclude_none=True),db,
                 mobile_file=mobile_file.model_dump(exclude_none=True) if mobile_file else None,
                 width=width,height=height)
        return approval(admin.subject,"banner",result["plan_id"],result,
                        previews=banner.get_previews(admin.subject,result["plan_id"]))

    @tool("likenovel_expansion_receipt")
    async def expansion_receipt(receipt_id: str) -> dict:
        admin=require(READ_OPERATIONS)
        if not re.fullmatch(r"(?:ai-reader-apply:[a-f0-9]{32}|promotion-apply:[a-f0-9-]{36}|mail:campaign:[a-f0-9]{32}|banner-publish:[a-f0-9-]{36})",receipt_id):
            raise ValueError("Only expansion operation receipts may be read")
        row=store.get(receipt_id,admin.subject)
        if row is None: raise ValueError("Receipt not found")
        if receipt_id.startswith("banner-publish:"):
            from app.services.ai import mcp_banner as banner
            return await banner.verify_public(admin.subject, receipt_id.removeprefix("banner-publish:"))
        if receipt_id.startswith("promotion-apply:"):
            return await promotion.verify_public(admin.subject, receipt_id.removeprefix("promotion-apply:"))
        if receipt_id.startswith("mail:"):
            return await mail.verify_sent(admin.subject,receipt_id)
        return {k:v for k,v in row.items() if k not in {"encrypted", "sealed", "nonce_hash"}}

    @tool("likenovel_execute_approved_expansion", private=True)
    async def execute_approved_expansion(approval_id: str, nonce: str) -> dict:
        """UI-only. Executes only after the user clicks the exact plan's approval button."""
        admin=identity()
        row=consume_approval(admin.subject,approval_id,nonce)
        scope,flag=ACTIONS[row["kind"]]
        require(scope)
        if load_config().get(flag) is not True:
            raise PermissionError("This expansion's write capability is disabled")
        if not store.consume(approval_id,admin.subject,"pending"):
            raise PermissionError("Approval already used")
        if row["kind"] == "ai-reader":
            return await readers.apply(admin.subject,row["plan_id"],authorized_plan_hash=row["summary"]["plan_hash"])
        if row["kind"] == "member-mail":
            mail.record_user_authorization(admin.subject,row["plan_id"],row["summary"]["content_hash"],
                source="approved_concrete_plan",evidence_ref=approval_id)
            async with likenovel_db_session() as db:
                return await mail.send_campaign(admin.subject,row["plan_id"],db)
        if row["kind"] == "banner":
            from app.services.ai import mcp_banner as banner
            async with likenovel_db_session() as db:
                return await banner.publish_prepared(admin.subject,row["plan_id"],db,
                    {"role":"admin","user_id":admin.admin_user_id},approved_plan_id=row["plan_id"],
                    scopes=admin.scopes,writes_enabled=True)
        actor={"role":"admin","user_id":admin.admin_user_id}
        if row["kind"] == "hundred-free":
            from app.services.ai import mcp_cp_auth as cp
            actor=await cp.get_actor(admin.subject)
        async with likenovel_db_session() as db:
            return await promotion.apply_plan(admin.subject,row["plan_id"],db,
                actor,approved_plan_id=row["plan_id"],scopes=admin.scopes,writes_enabled=True,
                expected_cp_company_name=load_config().get("cp_company_name"))

    @mcp.resource(UI_URI, mime_type="text/html+skybridge", meta={"openai/widgetDescription":
        "Shows the exact LikeNovel operation for user review. Only a user's explicit approval button executes it."})
    def approval_widget() -> str:
        return APPROVAL_HTML


APPROVAL_HTML = r"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>body{font:14px system-ui;color:#162638;padding:20px;max-width:760px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:16px;border-radius:12px}button{padding:12px 22px;background:#164866;color:white;border:0;border-radius:8px}button:disabled{opacity:.5}</style>
<h2>라이크노벨 실행 계획</h2><p>내용을 확인한 뒤 이 계획만 승인·실행하세요. 계획·대상·시안이 바뀌면 새 승인이 필요합니다.</p>
<div id="images"></div><pre id="plan">계획을 불러오는 중입니다.</pre><button id="approve" disabled>이 계획 승인하고 실행</button><p id="status" role="status"></p>
<script>
const plan=document.getElementById('plan'),button=document.getElementById('approve'),status=document.getElementById('status');
let approval=null,submitted=false,summary=null;
function describe(s){
 if(s.body!==undefined)return ['발신: '+s.sender,'제목: '+s.subject,'대상: '+s.recipient_count+'명 (수신자는 서로 공개되지 않습니다)','대상 조건: '+JSON.stringify(s.filters),'',s.body].join('\n');
 if(s.starts_on)return ['AI 독자 '+s.count+'명','기간: '+s.starts_on+' ~ '+s.ends_on+' (한국시간, '+s.duration_days+'일)','운영: '+({resume:'일시중지 독자 재개',restart:'전체 독자 재설정',bootstrap:'전용 독자 구성'}[s.mode]||s.mode),s.restart_affects_all_existing_agents?'전체 재설정은 기존 '+s.existing_agent_count+'명에도 영향을 줍니다.':'요청한 독자만 구성합니다.'].join('\n');
 const r=s.request||{},p=s.before?.product||{};
 if(s.operation==='banner')return ['배너: '+r.title,'위치: '+r.position+(r.division?' / '+r.division:''),'표시 순서: '+r.show_order,'노출: '+r.show_start_date+' 0시 ~ '+r.show_end_date+' 0시 (한국시간, 종료 시각 제외)','링크: '+r.url,'이미지 규격: '+JSON.stringify(Object.fromEntries(Object.entries(s.assets||{}).map(([k,v])=>[k,v.size])))].join('\n');
 if(s.operation==='hundred-free')return ['100화 무료 프로모션: '+p.title,'무료 범위: 1~100화','시작: 승인 후 즉시','종료: '+r.hundred_free_campaign_ends_at+' (한국시간)','기간 종료 후 기존 정책대로 1~25화 무료, 26화부터 유료로 복원됩니다.'].join('\n');
 if(s.operation==='paid-conversion')return ['유료 전환: '+p.title,'유료 시작: '+r.paid_episode_no+'화','설정 저장 후 기존 배치가 실제 가격을 반영하며, 닷이 결과를 별도로 확인합니다.'].join('\n');
 if(s.operation==='paid-approval')return ['유료전환 심사 승인: '+p.title,'심사 승인만 처리합니다. 실제 유료 시작 회차 설정은 별도 계획입니다.'].join('\n');
 return JSON.stringify(s,null,2);
}
function render(){const raw=window.openai?.toolResponseMetadata;const meta=raw?._meta||raw?.mcp_tool_result?._meta||raw?.call_tool_result?._meta||raw;if(!meta?.approval)return;approval=meta.approval;summary=meta.summary;plan.textContent=describe(summary);const images=document.getElementById('images');images.replaceChildren();for(const url of meta.images||[]){if(!/^data:image\/(webp|png|jpeg);base64,/.test(url))continue;const img=document.createElement('img');img.src=url;img.alt='게시 예정 배너 시안';img.style.maxWidth='100%';images.append(img);}button.disabled=submitted;}
window.addEventListener('openai:set_globals',render);render();
button.addEventListener('click',async()=>{if(!approval||submitted)return;submitted=true;button.disabled=true;status.textContent='승인된 계획을 실행하고 결과를 확인하고 있습니다.';
try{const result=await window.openai.callTool('likenovel_execute_approved_expansion',{approval_id:approval.id,nonce:approval.nonce});
status.textContent='실행 응답을 받았습니다. 닷이 실제 적용·노출 결과를 확인하도록 요청합니다.';if(window.openai.sendFollowUpMessage&&summary?.result_receipt_id)await window.openai.sendFollowUpMessage({prompt:'사용자가 방금 실행 계획을 승인했습니다. '+summary.result_receipt_id+' 영수증을 읽기 전용으로 조회해 실제 결과를 한국어로 보고해주세요. 완료 여부를 추정하지 말고 불확실하면 다시 실행하지 마세요.'});}
catch(error){status.textContent='실행 결과를 확인해야 합니다. 다시 실행하지 말고 닷에 결과 영수증 조회를 요청하세요.';}});
</script></html>"""
