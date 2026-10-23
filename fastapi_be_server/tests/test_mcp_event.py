import copy
import io
import os
import re
import socket
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from PIL import Image
from app.models.product import Product as ProductModel

from app.services.ai import mcp_event as event, mcp_extensions as ext, mcp_store as store


def image_bytes(size=(1080, 347)):
    stream = io.BytesIO()
    Image.new("RGB", size, "blue").save(stream, format="PNG")
    return stream.getvalue()


def request():
    return dict(title="10월 2주차 유료화 신작", start_date="2026-10-05", end_date="2026-10-12",
        type="etc", show_yn_thumbnail_img="Y", show_yn_detail_img="Y", show_yn_product="Y",
        show_yn_information="Y", thumbnail_image_id=11, detail_image_id=12, account_name="유료화 신작",
        product_ids=[1235], information="유료화 신작을 만나보세요.")


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows, self.value = list(rows), scalar
    def mappings(self):
        return self
    def all(self):
        return self.rows
    def first(self):
        return self.rows[0] if self.rows else None
    def one_or_none(self):
        return self.first()
    def scalar_one(self):
        return self.value


class Transaction:
    def __init__(self, db):
        self.db = db
    async def __aenter__(self):
        self.before = copy.deepcopy(self.db.events)
        return self
    async def __aexit__(self, kind, error, trace):
        if kind:
            self.db.events = self.before
        elif self.db.commit_error:
            raise RuntimeError("simulated lost commit acknowledgement")
        return False


class DB:
    """In-memory external DB boundary; native CMS insert/update code remains real."""
    def __init__(self):
        self.events = {}
        self.products = {1235: dict(product_id=1235, title="실제 작품", open_yn="Y", blind_yn="N",
            price_type="paid", status_code="ongoing", paid_open_date=datetime(2026, 10, 8, 10))}
        self.images = {n: dict(file_group_id=n, group_type="user", use_yn="Y", item_use_yn="Y",
            file_name=str(n)+".png", file_org_name=str(n)+".png",
            file_path="https://cdn.likenovel.net/user/"+str(n)+".png") for n in (11, 12)}
        self.calls, self.writes, self.last_id, self.commit_error = [], 0, 20, False
    def begin(self):
        return Transaction(self)
    async def execute(self, query, params=None):
        sql = " ".join(str(query).split())
        params = params or {}
        self.calls.append((sql, copy.deepcopy(params)))
        if "LAST_INSERT_ID()" in sql:
            return Result(scalar=self.last_id)
        if "INSERT INTO tb_event_v2" in sql:
            self.writes += 1
            self.last_id += 1
            self.events[self.last_id] = self.row(self.last_id, params)
            return Result()
        if sql.lower().startswith("update tb_event_v2"):
            self.writes += 1
            self.events[params["id"]].update({k: v for k, v in params.items() if k != "id"})
            return Result()
        if "tb_common_file" in sql and "FROM tb_event_v2" not in sql:
            ids = [value for value in params.values() if type(value) is int]
            return Result([self.images[n] for n in ids if n in self.images])
        if "FROM tb_product" in sql and "FROM tb_event_v2" not in sql:
            selected = re.search(r"SELECT (.+?) FROM tb_product",sql).group(1)
            columns = {value.strip().split(".")[-1] for value in selected.split(",")}
            unknown = columns - set(ProductModel.__table__.columns.keys())
            if unknown:
                raise AssertionError("Product query uses fields absent from the real ORM: "+str(sorted(unknown)))
            if "paid_open_date >=" in sql:
                return Result(list(self.products.values()))
            ids = [value for value in params.values() if type(value) is int]
            return Result([self.products[n] for n in ids if n in self.products])
        if "COUNT(*)" in sql:
            return Result([{"total_count": len(self.events)}])
        if "FROM tb_event_v2" in sql:
            if "id" in params:
                return Result([self.events[params["id"]]] if params["id"] in self.events else [])
            selected = re.search(r"WHERE id = (\d+)", sql)
            if selected:
                event_id = int(selected.group(1))
                return Result([self.public(event_id)] if event_id in self.events else [])
            return Result(list(self.events.values()))
        raise AssertionError("Unexpected SQL: "+sql)
    def public(self, event_id):
        row = copy.deepcopy(self.events[event_id])
        for label in ("thumbnail", "detail"):
            row[label+"_image_path"] = self.images[row[label+"_image_id"]]["file_path"]
        return row
    @staticmethod
    def row(event_id, data):
        row = {key: None for key in event.PostEventReqBody.model_fields}
        row.update(data)
        row.update(id=event_id, created_date=datetime(2026, 10, 1), updated_date=None,
                   created_id=-1, updated_id=None)
        return row


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.dict(os.environ, {"LIKENOVEL_MCP_STATE_DB": self.tmp.name+"/receipts.db"}),
            patch.object(event, "load_config", return_value={"resource": "https://api.likenovel.net/mcp"}),
            patch.object(ext, "load_config", return_value={"resource": "https://api.likenovel.net/mcp",
                                                          "event_writes_enabled": True}),
            patch.object(event.settings, "R2_SC_CDN_URL", "https://cdn.likenovel.net"),
            patch.object(event.banner, "_download", return_value=image_bytes()),
            patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden in tests")),
        ]
        for item in self.patches:
            item.start()
        self.db = DB()
    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()
    async def prepare(self, data=None, **kwargs):
        return await event.prepare("owner", request() if data is None else data, self.db,
            idempotency_key=kwargs.pop("idempotency_key", "one-request"), **kwargs)
    async def apply(self, plan, **kwargs):
        return await event.apply_plan("owner", plan["plan_id"], self.db, {"role":"admin","user_id":1},
            approved_plan_id=plan["plan_id"], approved_plan_hash=plan["plan_hash"],
            scopes=[event.WRITE_EVENT], writes_enabled=True, **kwargs)

    async def test_prepare_is_read_only_and_freezes_separate_images_products_and_link(self):
        plan = await self.prepare(week_start="2026-10-05")
        self.assertEqual(self.db.writes, 0)
        self.assertEqual(plan["references"]["products"][0]["product_id"], 1235)
        self.assertEqual(plan["references"]["images"]["thumbnail"]["file_group_id"], 11)
        self.assertEqual(plan["references"]["images"]["detail"]["file_group_id"], 12)
        self.assertEqual(plan["references"]["images"]["thumbnail"]["size"], [1080,347])
        self.assertIn("/product/event/{event_id}", plan["event_url"])
        self.assertFalse(plan["publishes_home_banner"])
        self.assertEqual(store.get("event-plan:"+plan["plan_id"], "other"), None)

    async def test_same_idempotency_key_returns_frozen_plan_and_changed_input_fails(self):
        first = await self.prepare()
        self.assertEqual(await self.prepare(), first)
        with self.assertRaisesRegex(ValueError, "idempotency"):
            await self.prepare({**request(), "title":"changed"})

    async def test_invalid_dates_ids_flags_types_and_unknown_fields_fail_before_writes(self):
        for patch_value in ({"start_date":"20261005"}, {"start_date":"2026-02-30"},
            {"end_date":"2026-10-01"}, {"product_ids":[True]}, {"product_ids":[1235,1235]},
            {"product_ids":[0]}, {"thumbnail_image_id":True}, {"show_yn_product":"yes"},
            {"type":"etc' OR 1=1"}, {"url":"https://evil.test"}, {"detail_image_id":11}):
            with self.subTest(value=patch_value), self.assertRaises(ValueError):
                await self.prepare({**request(), **patch_value})
        self.assertEqual(self.db.writes, 0)
        same_day = await self.prepare({**request(), "end_date":"2026-10-05"})
        self.assertEqual(same_day["request"]["end_date"], "2026-10-05")

    async def test_missing_hidden_references_and_week_mismatch_are_rejected(self):
        for change in ("missing-product", "hidden-product", "blind-product", "missing-image", "hidden-image", "week"):
            db = self.db
            if change == "missing-product": db.products.clear()
            if change == "hidden-product": db.products[1235]["open_yn"] = "N"
            if change == "blind-product": db.products[1235]["blind_yn"] = "Y"
            if change == "missing-image": db.images.pop(12)
            if change == "hidden-image": db.images[12]["item_use_yn"] = "N"
            if change == "week": db.products[1235]["paid_open_date"] = datetime(2026,10,12)
            with self.subTest(change=change), self.assertRaises(ValueError):
                await self.prepare(week_start="2026-10-05")
            self.db = DB()

    async def test_image_bytes_format_and_advisory_dimensions_are_reported(self):
        with patch.object(event.banner, "_download", return_value=b"invalid"):
            with self.assertRaises(ValueError):
                await self.prepare()
        with patch.object(event.banner, "_download", return_value=image_bytes((1120,1600))):
            plan = await self.prepare()
        asset = plan["references"]["images"]["detail"]
        self.assertEqual(asset["size"], [1120,1600])
        self.assertFalse(asset["matches_cms_guide"])

    async def test_asset_and_destination_urls_are_exact_and_environment_bound(self):
        for bad in ("https://127.0.0.1/x", "http://cdn.likenovel.net/x",
                    "https://cdn.likenovel.net.evil.test/x",
                    "https://user:password@cdn.likenovel.net/x",
                    "https://cdn.likenovel.net/x?token=private"):
            self.db.images[11]["file_path"] = bad
            with self.subTest(url=bad), self.assertRaises(ValueError):
                await self.prepare()
        self.db = DB()
        self.db.events[10] = DB.row(10, request())
        with self.assertRaises(ValueError):
            await self.prepare({"title":"changed"}, event_id=10, event_url="https://likenovel.net/product/event/11")
        plan = await self.prepare({"title":"changed"}, event_id=10,
            event_url="https://likenovel.net/product/event/10")
        self.assertEqual(plan["event_url"], "https://likenovel.net/product/event/10")

    async def test_create_and_update_use_native_cms_with_transactional_readback(self):
        plan = await self.prepare()
        result = await self.apply(plan)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["committed"])
        self.assertEqual(result["event_id"], 21)
        self.assertEqual(result["after"]["product_ids"], "[1235]")
        self.assertEqual(self.db.writes, 1)
        self.assertEqual((await self.apply(plan))["event_id"], 21)
        self.assertEqual(self.db.writes, 1)
        updated = await self.prepare({"title":"수정 제목"}, event_id=21, idempotency_key="update-one")
        result = await self.apply(updated)
        self.assertEqual(result["after"]["title"], "수정 제목")
        self.assertEqual(self.db.writes, 2)
        self.assertTrue(any("FOR UPDATE" in sql and "tb_event_v2" in sql for sql,_ in self.db.calls))
        self.assertFalse(any("tb_carousel_banner" in sql for sql,_ in self.db.calls))

    async def test_native_update_cannot_silently_clear_nullable_fields(self):
        self.db.events[10] = DB.row(10, {**request(), "reward_type":"cash"})
        with self.assertRaisesRegex(ValueError, "null"):
            await self.prepare({"reward_type":None}, event_id=10)

    async def test_concurrent_event_product_image_edits_stop_before_cms_write(self):
        self.db.events[10] = DB.row(10, request())
        for mutation in ("event", "product", "image", "pixels"):
            plan = await self.prepare({"title":"변경"}, event_id=10, idempotency_key=mutation)
            original = copy.deepcopy((self.db.events,self.db.products,self.db.images))
            if mutation == "event": self.db.events[10]["information"] = "concurrent editor"
            if mutation == "product": self.db.products[1235]["paid_open_date"] = datetime(2026,10,9)
            if mutation == "image": self.db.images[11]["file_name"] = "changed.png"
            with patch.object(event.banner,"_download",
                return_value=image_bytes((1080,348)) if mutation=="pixels" else image_bytes()):
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    await self.apply(plan)
            self.assertEqual(self.db.writes,0)
            self.db.events,self.db.products,self.db.images = original

    async def test_plan_tamper_hash_wrong_owner_and_expiry_are_rejected(self):
        plan = await self.prepare()
        with self.assertRaises(ValueError):
            await event.apply_plan("other", plan["plan_id"], self.db, {"role":"admin","user_id":1},
                approved_plan_id=plan["plan_id"], approved_plan_hash=plan["plan_hash"],
                scopes=[event.WRITE_EVENT], writes_enabled=True)
        with patch.object(event.time,"time",return_value=plan["expires_at"]+1):
            with self.assertRaises(ValueError):
                await self.apply(plan)
        row = store.get("event-plan:"+plan["plan_id"],"owner")
        row = {k:v for k,v in row.items() if k not in ("job_id","status","updated_at")}
        row["request"]["title"] = "tampered"
        store.save("event-plan:"+plan["plan_id"],"owner","ready",row)
        with self.assertRaises(ValueError):
            await self.apply(plan)
        self.assertEqual(self.db.writes,0)

    async def test_write_scope_switch_and_exact_hash_are_required(self):
        plan = await self.prepare()
        for values in ({"scopes":[]}, {"writes_enabled":False}, {"approved_plan_hash":"wrong"},
                       {"approved_plan_id":"wrong"}):
            options = dict(approved_plan_id=plan["plan_id"], approved_plan_hash=plan["plan_hash"],
                scopes=[event.WRITE_EVENT], writes_enabled=True)
            options.update(values)
            with self.subTest(values=values), self.assertRaises(PermissionError):
                await event.apply_plan("owner",plan["plan_id"],self.db,{"role":"admin","user_id":1},**options)
        self.assertEqual(self.db.writes,0)

    async def test_commit_ack_loss_is_uncertain_and_never_reapplies(self):
        plan = await self.prepare()
        self.db.commit_error = True
        result = await self.apply(plan)
        self.assertEqual(result["status"],"uncertain")
        self.assertIsNone(result["committed"])
        self.db.commit_error = False
        with self.assertRaisesRegex(ValueError,"readback"):
            await self.apply(plan)
        self.assertEqual(self.db.writes,1)
        with patch.object(event,"_public_detail",AsyncMock(return_value={"data":self.db.public(21)})):
            result = await event.verify_receipt("owner",plan["plan_id"],self.db)
        self.assertTrue(result["committed"])
        self.assertEqual(self.db.writes,1)

    async def test_readback_failure_rolls_back_and_receipt_reports_failed_without_retry(self):
        plan = await self.prepare()
        original = event.service.post_event
        async def wrong(payload, db):
            await original(payload,db)
            db.events[db.last_id]["title"] = "wrong"
        with patch.object(event.service,"post_event",wrong):
            result = await self.apply(plan)
        self.assertEqual(result["status"],"failed")
        self.assertFalse(result["committed"])
        self.assertEqual(self.db.events,{})
        with self.assertRaises(ValueError):
            await self.apply(plan)

    async def test_receipt_reads_fresh_db_and_reports_partial_public_failure(self):
        plan = await self.prepare()
        await self.apply(plan)
        with patch.object(event,"_public_detail",AsyncMock(side_effect=ValueError("unavailable"))):
            result = await event.verify_receipt("owner",plan["plan_id"],self.db)
        self.assertTrue(result["committed"])
        self.assertFalse(result["public_verified"])
        self.assertTrue(result["partial_success"])
        with patch.object(event,"_public_detail",AsyncMock(return_value={"data":self.db.public(21)})):
            result = await event.verify_receipt("owner",plan["plan_id"],self.db)
        self.assertTrue(result["public_verified"])
        self.db.events[21]["title"] = "changed later"
        result = await event.verify_receipt("owner",plan["plan_id"],self.db)
        self.assertFalse(result["db_verified"])
        self.assertFalse(result["public_verified"])
        self.assertEqual(self.db.writes,1)

    async def test_weekly_paid_open_groups_use_kst_and_exact_boundaries(self):
        self.db.products[2] = {**self.db.products[1235],"product_id":2,
                               "paid_open_date":datetime(2026,10,12)}
        result = await event.paid_open_weeks(self.db,"2026-10-05","2026-10-19")
        self.assertEqual(result["timezone"],"Asia/Seoul")
        self.assertEqual([r["week_start"] for r in result["weeks"]],["2026-10-05","2026-10-12"])
        self.assertEqual(result["weeks"][0]["products"][0]["product_id"],1235)
        with self.assertRaises(ValueError):
            await event.paid_open_weeks(self.db,"2026-10-05","2027-10-05")

    async def test_registered_event_tools_and_separate_private_execution_preserve_old_scopes(self):
        server = FastMCP("test")
        ext.register(server,lambda:SimpleNamespace(subject="owner",admin_user_id=1,scopes=ext.EXTRA_SCOPES))
        tools = {t.name:t for t in await server.list_tools()}
        for name in ("likenovel_events","likenovel_event_detail","likenovel_paid_open_weeks",
                     "likenovel_prepare_event","likenovel_execute_approved_event"):
            self.assertIn(name,tools)
        old = tools["likenovel_execute_approved_expansion"].meta["securitySchemes"][0]["scopes"]
        self.assertNotIn(event.WRITE_EVENT,old)
        private = tools["likenovel_execute_approved_event"]
        self.assertEqual(private.meta["ui"]["visibility"],["app"])
        self.assertIn(event.WRITE_EVENT,private.meta["securitySchemes"][0]["scopes"])
        plan = await self.prepare()
        result = ext.approval("owner","event",plan["plan_id"],plan)
        hidden = result.meta["approval"]
        admin = SimpleNamespace(subject="owner",admin_user_id=1,scopes=[ext.READ_OPERATIONS,event.WRITE_EVENT])
        args={"approval_id":hidden["id"],"nonce":hidden["nonce"]}
        with patch.object(ext,"likenovel_db_session",return_value=Session(self.db)):
            await server.call_tool("likenovel_execute_approved_event",args)
        self.assertTrue(store.get("event-apply:"+plan["plan_id"],"owner")["committed"])
        with self.assertRaises(ToolError):
            await server.call_tool("likenovel_execute_approved_event",args)
        self.assertEqual(self.db.writes,1)

    async def test_list_and_detail_reuse_cms_and_reject_unsafe_filters(self):
        self.db.events[10] = DB.row(10, request())
        listed = await event.events_list(self.db, "all", 1, 20)
        self.assertEqual(listed["results"][0]["id"], 10)
        detail = await event.event_detail(self.db, 10)
        self.assertEqual(detail["event"]["title"], request()["title"])
        self.assertEqual(detail["event_url"], "https://likenovel.net/product/event/10")
        for value in ("all' OR 1=1", [], None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                await event.events_list(self.db, value)
        for page, count in ((0,20),(True,20),(1,101),(1,-1)):
            with self.assertRaises(ValueError):
                await event.events_list(self.db,"all",page,count)
        with self.assertRaises(ValueError):
            await event.event_detail(self.db,True)
        self.assertEqual(self.db.writes,0)

    async def test_reward_event_uses_existing_cms_fields_and_references(self):
        self.db.products[2] = {**self.db.products[1235],"product_id":2}
        data = {**request(),"type":"view-3-times","target_product_ids":[2],
                "reward_type":"ticket","reward_amount":1,"reward_max_people":10}
        plan = await self.prepare(data)
        result = await self.apply(plan)
        self.assertEqual(result["after"]["target_product_ids"],"[2]")
        self.assertEqual(result["after"]["reward_type"],"ticket")
        self.assertEqual({row["product_id"] for row in plan["references"]["products"]},{2,1235})
        with self.assertRaises(ValueError):
            await self.prepare({**data,"reward_amount":0},idempotency_key="invalid-reward")

    async def test_concurrent_workers_cannot_create_twice(self):
        import asyncio
        plan = await self.prepare()
        results = await asyncio.gather(self.apply(plan),self.apply(plan),return_exceptions=True)
        self.assertEqual(self.db.writes,1)
        self.assertEqual(sum(isinstance(value,dict) and value.get("committed") is True for value in results),1)
        self.assertEqual(sum(isinstance(value,ValueError) for value in results),1)

    async def test_public_readback_calls_only_verified_get_endpoint(self):
        from httpx import AsyncClient as HTTPClient, MockTransport, Response
        plan = await self.prepare()
        await self.apply(plan)
        calls = []
        def handle(req):
            calls.append((req.method,str(req.url)))
            return Response(200,json=event._clean({"data":self.db.public(21)}))
        transport = MockTransport(handle)
        with patch.object(event,"AsyncClient",side_effect=lambda **options:
                          HTTPClient(transport=transport,**options)) as factory:
            result = await event.verify_receipt("owner",plan["plan_id"],self.db)
        self.assertEqual(calls,[("GET","https://api.likenovel.net/v1/query/events/21")])
        self.assertFalse(factory.call_args.kwargs["follow_redirects"])
        self.assertFalse(factory.call_args.kwargs["trust_env"])
        self.assertTrue(result["public_verified"])
        self.assertEqual(self.db.writes,1)

    async def test_public_product_image_or_content_mismatch_is_partial_success(self):
        plan = await self.prepare()
        await self.apply(plan)
        for bad in ({"product_ids":"[]"},{"product_ids":"not-json"},{"product_ids":[1235.0]},
                    {"title":"stale"},{"detail_image_path":"https://evil.test/x"}):
            with patch.object(event,"_public_detail",AsyncMock(return_value={"data":{**self.db.public(21),**bad}})):
                result = await event.verify_receipt("owner",plan["plan_id"],self.db)
            self.assertTrue(result["committed"])
            self.assertFalse(result["public_verified"])
            self.assertTrue(result["partial_success"])
        self.assertEqual(self.db.writes,1)

    async def test_db_readback_failure_preserves_committed_receipt(self):
        plan = await self.prepare()
        await self.apply(plan)
        with patch.object(self.db,"execute",AsyncMock(side_effect=RuntimeError("DB unavailable"))):
            result = await event.verify_receipt("owner",plan["plan_id"],self.db)
        self.assertTrue(result["committed"])
        self.assertEqual(result["verification_status"],"db_readback_failed")
        self.assertFalse(result["db_verified"])
        self.assertFalse(result["retry_allowed"])
        self.assertTrue(result["partial_success"])

    async def test_event_button_execution_requires_nonce_scope_and_switch(self):
        admin = SimpleNamespace(subject="owner",admin_user_id=1,scopes=[ext.READ_OPERATIONS])
        server = FastMCP("test")
        ext.register(server,lambda:admin)
        plan = await self.prepare()
        prepared = ext.approval("owner","event",plan["plan_id"],plan)
        hidden = prepared.meta["approval"]
        args = {"approval_id":hidden["id"],"nonce":hidden["nonce"]}
        for changes in ({"nonce":"wrong"},{}):
            with self.assertRaises(ToolError):
                await server.call_tool("likenovel_execute_approved_event",{**args,**changes})
        admin.scopes.append(event.WRITE_EVENT)
        with patch.object(ext,"load_config",return_value={"event_writes_enabled":False}):
            with self.assertRaises(ToolError):
                await server.call_tool("likenovel_execute_approved_event",args)
        self.assertEqual(store.get(hidden["id"],"owner")["status"],"pending")
        with self.assertRaises(ToolError):
            await server.call_tool("likenovel_execute_approved_expansion",args)
        self.assertEqual(self.db.writes,0)
        with patch.object(ext,"likenovel_db_session",return_value=Session(self.db)):
            await server.call_tool("likenovel_execute_approved_event",args)
        self.assertEqual(self.db.writes,1)
        with self.assertRaises(ToolError):
            await server.call_tool("likenovel_execute_approved_event",args)

    async def test_event_scope_is_not_granted_by_legacy_banner_scope(self):
        from app.services.ai import mcp_promotion
        plan = await self.prepare()
        with self.assertRaises(PermissionError):
            await event.apply_plan("owner",plan["plan_id"],self.db,{"role":"admin","user_id":1},
                approved_plan_id=plan["plan_id"],approved_plan_hash=plan["plan_hash"],
                scopes=[mcp_promotion.BANNER_SCOPE],writes_enabled=True)
        self.assertEqual(self.db.writes,0)

    async def test_environment_mismatch_and_timestamps_fail_closed(self):
        for resource in ("https://api.likenovel.net/mcp?token=hidden","http://api.likenovel.net/mcp",
                         "https://evil.test/mcp","https://user@api.likenovel.net/mcp"):
            with patch.object(event,"load_config",return_value={"resource":resource}):
                with self.assertRaises(ValueError):
                    await self.prepare()
        with self.assertRaises(ValueError):
            await self.prepare({**request(),"start_date":"2026-10-05T00:00:00+09:00"})
        self.db.events[10] = DB.row(10,{**request(),"end_date":"2026-10-12 23:59:59"})
        with self.assertRaises(ValueError):
            await self.prepare({"title":"changed"},event_id=10)

    def test_event_widget_waits_for_explicit_click_and_uses_scoped_tool(self):
        import subprocess
        script = ext.APPROVAL_HTML.split("<script>",1)[1].split("</script>",1)[0]
        harness = r"""
const vm=require('node:vm');
(async()=>{
 const events={},elements={};let calls=[];
 for(const id of ['plan','approve','status','images'])elements[id]={disabled:true,style:{},textContent:'',addEventListener:(n,f)=>events[id+':'+n]=f,replaceChildren:()=>{},append:()=>{}};
 const hidden={approval:{id:'event-plan',nonce:'only-component'},
 summary:{operation:'event',action:'create',request:{title:'<img src=x onerror=evil>'}},images:[]};
 const context={document:{getElementById:id=>elements[id],createElement:()=>({style:{}})},
 window:{openai:{toolResponseMetadata:hidden,callTool:async(name,args)=>{calls.push({name,args});return {}}},
 addEventListener:()=>{}},JSON};
 vm.runInNewContext(process.argv[1],context);
 if(calls.length!==0||elements.approve.disabled||!elements.plan.textContent.includes('<img'))throw Error('unsafe hydration');
 await events['approve:click']();await events['approve:click']();
 if(calls.length!==1||calls[0].name!=='likenovel_execute_approved_event'||calls[0].args.nonce!=='only-component')throw Error('wrong execution');
})().catch(e=>{console.error(e.message);process.exit(1)});
"""
        result = subprocess.run(["node","-e",harness,script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


    async def test_existing_grant_and_other_write_switches_remain_unchanged(self):
        old_scopes = [value for value in ext.EXTRA_SCOPES if value != event.WRITE_EVENT]
        store.save("oauth:grant:existing","owner","active",
                   {"scopes":old_scopes,"admin_user_id":1})
        before = store.get("oauth:grant:existing","owner")
        config = {"resource":"https://api.likenovel.net/mcp","event_writes_enabled":True,
                  "banner_writes_enabled":False,"promotion_writes_enabled":False}
        original_config = copy.deepcopy(config)
        plan = await self.prepare()
        approval = ext.approval("owner","event",plan["plan_id"],plan)
        hidden = approval.meta["approval"]
        admin = SimpleNamespace(subject="owner",admin_user_id=1,scopes=[ext.READ_OPERATIONS,event.WRITE_EVENT])
        server=FastMCP("test")
        ext.register(server,lambda:admin)
        with patch.object(ext,"load_config",return_value=config), \
             patch.object(ext,"likenovel_db_session",return_value=Session(self.db)):
            await server.call_tool("likenovel_execute_approved_event",
                {"approval_id":hidden["id"],"nonce":hidden["nonce"]})
        self.assertTrue(store.get("event-apply:"+plan["plan_id"],"owner")["committed"])
        self.assertEqual(store.get("oauth:grant:existing","owner"),before)
        self.assertEqual(config,original_config)

    async def test_readback_cannot_overwrite_a_newer_execution_receipt(self):
        plan = await self.prepare()
        await self.apply(plan)
        op = "event-apply:"+plan["plan_id"]
        async def public_after_writer_progress(event_id):
            latest = store.get(op,"owner")
            store.save(op,"owner","completed",
                {**event._payload(latest),"writer_marker":"newer-execution-receipt"})
            return {"data":self.db.public(event_id)}
        with patch.object(event,"_public_detail",side_effect=public_after_writer_progress):
            await event.verify_receipt("owner",plan["plan_id"],self.db)
        self.assertEqual(store.get(op,"owner").get("writer_marker"),"newer-execution-receipt")

    async def test_in_progress_receipt_lookup_never_interferes_with_writer(self):
        plan = await self.prepare()
        op = "event-apply:"+plan["plan_id"]
        store.claim(op,"owner",{"kind":"event","plan_id":plan["plan_id"],"event_id":None,
            "phase":"applying","committed":False})
        before = store.get(op,"owner")
        with patch.object(self.db,"execute",AsyncMock()) as query:
            result = await event.verify_receipt("owner",plan["plan_id"],self.db)
        query.assert_not_awaited()
        self.assertEqual(result["verification_status"],"execution_in_progress")
        self.assertEqual(store.get(op,"owner"),before)

    async def test_uncertain_commit_requires_the_full_persisted_after_snapshot(self):
        plan = await self.prepare()
        receipt = await self.apply(plan)
        op = "event-apply:"+plan["plan_id"]
        store.save(op,"owner","uncertain",{**event._payload(receipt),
            "committed":None,"phase":"commit_readback_required"})
        self.db.events[21]["updated_id"] = 99
        with patch.object(event,"_public_detail",AsyncMock()) as public:
            result = await event.verify_receipt("owner",plan["plan_id"],self.db)
        self.assertEqual(result["status"],"uncertain")
        self.assertIsNone(result["committed"])
        public.assert_not_awaited()

    async def test_unchanged_update_is_read_only_and_does_not_create_an_execution_plan(self):
        self.db.events[10] = DB.row(10,request())
        with self.assertRaisesRegex(ValueError,"No event fields change"):
            await self.prepare({"title":request()["title"]},event_id=10)
        self.assertEqual(self.db.writes,0)

    async def test_missing_or_non_boolean_event_flag_cannot_execute(self):
        admin = SimpleNamespace(subject="owner",admin_user_id=1,
            scopes=[ext.READ_OPERATIONS,event.WRITE_EVENT])
        server = FastMCP("test")
        ext.register(server,lambda:admin)
        plan = await self.prepare()
        result = ext.approval("owner","event",plan["plan_id"],plan)
        hidden = result.meta["approval"]
        for flag in ({},{"event_writes_enabled":False},{"event_writes_enabled":1},
                     {"event_writes_enabled":"true"}):
            with patch.object(ext,"load_config",return_value=flag):
                with self.assertRaises(ToolError):
                    await server.call_tool("likenovel_execute_approved_event",
                        {"approval_id":hidden["id"],"nonce":hidden["nonce"]})
        self.assertEqual(store.get(hidden["id"],"owner")["status"],"pending")
        self.assertEqual(self.db.writes,0)

    async def test_oauth_default_scopes_exclude_event_and_explicit_scopes_are_frozen(self):
        from app.services.ai import mcp_oauth as oauth
        from urllib.parse import urlsplit,parse_qs
        config = {"allowed_subject":"owner","resource":"https://api.likenovel.net/mcp",
                  "oauth_callback":"https://chatgpt.com/connector/oauth/test-exact"}
        provider = oauth.AdminOAuthProvider()
        with patch.object(oauth,"load_config",return_value=config):
            client = await provider.get_client("likenovel-dot-mcp")
            for requested in (None,list(oauth.SCOPES)):
                params = oauth.AuthorizationParams(state="test-state",scopes=requested,
                    code_challenge="a"*43,redirect_uri=config["oauth_callback"],
                    redirect_uri_provided_explicitly=True,resource=config["resource"])
                url = await provider.authorize(client,params)
                flow = parse_qs(urlsplit(url).query)["flow"][0]
                saved = store.get(oauth._key("flow",flow),"owner")["params"]["scopes"]
                self.assertIsInstance(saved,list)
                self.assertEqual(event.WRITE_EVENT in saved,requested is not None)
        self.assertNotIn(event.WRITE_EVENT,oauth.DEFAULT_SCOPES)
        self.assertIn(event.WRITE_EVENT,oauth.SCOPES)

    async def test_image_contract_identifies_each_cms_field_and_its_consumer(self):
        plan = await self.prepare()
        fields = plan["image_guide"]["fields"]
        self.assertEqual(fields["thumbnail_image_id"]["role"],"event_list_thumbnail")
        self.assertEqual(fields["detail_image_id"]["role"],"event_detail_body")
        for field in fields.values():
            self.assertEqual(field["cms_displayed_sizes"],[[1080,347],[1120,360]])
            self.assertIn("cms/app/events/add/page.tsx",field["cms_sources"][0])
        self.assertIn("height:auto",fields["detail_image_id"]["public_rendering"])
        self.assertTrue(plan["image_guide"]["home_banner"]["separate_asset"])

    async def test_registered_prepare_is_read_only_and_reaches_existing_approval_contract(self):
        admin=SimpleNamespace(subject="owner",admin_user_id=1,scopes=[ext.READ_OPERATIONS])
        server=FastMCP("test")
        ext.register(server,lambda:admin)
        with patch.object(ext,"likenovel_db_session",return_value=Session(self.db)):
            await server.call_tool("likenovel_prepare_event",
                {"request":request(),"idempotency_key":"registered-prepare"})
        with store.connection() as state:
            count=state.execute("SELECT COUNT(*) FROM receipts WHERE job_id LIKE 'extension-approval:%' AND status='pending'").fetchone()[0]
        self.assertEqual(count,1)
        self.assertEqual(self.db.writes,0)

    async def test_registered_event_ids_reject_boolean_before_any_database_access(self):
        admin=SimpleNamespace(subject="owner",admin_user_id=1,scopes=[ext.READ_OPERATIONS])
        server=FastMCP("test")
        ext.register(server,lambda:admin)
        for name,args in (("likenovel_event_detail",{"event_id":True}),
                          ("likenovel_prepare_event",{"request":request(),"idempotency_key":"bad-id","event_id":True})):
            with patch.object(ext,"likenovel_db_session",return_value=Session(self.db)) as session:
                with self.assertRaises(ToolError):
                    await server.call_tool(name,args)
                session.assert_not_called()


class Session:
    def __init__(self,db):
        self.db = db
    async def __aenter__(self):
        return self.db
    async def __aexit__(self,*args):
        pass


if __name__ == "__main__":
    unittest.main()
