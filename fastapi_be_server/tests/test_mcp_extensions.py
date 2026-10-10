import json
import os
import tempfile
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from app.services.ai import mcp_extensions as ext, mcp_store as store

class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"LIKENOVEL_MCP_STATE_DB":self.temp.name+"/state.sqlite3"})
        self.env.start()
    def tearDown(self):
        self.env.stop();self.temp.cleanup()
    def test_wire_hides_nonce_from_model_and_binds_owner(self):
        result=ext.approval("owner","ai-reader","plan",{"plan_hash":"exact","count":3})
        wire=result.model_dump(mode="json",by_alias=True)
        nonce=wire["_meta"]["approval"]["nonce"]
        visible=json.dumps({"content":wire["content"],"structuredContent":wire["structuredContent"]})
        self.assertNotIn(nonce,visible)
        key=wire["_meta"]["approval"]["id"]
        self.assertEqual(ext.consume_approval("owner",key,nonce)["plan_id"],"plan")
        with self.assertRaises(PermissionError):ext.consume_approval("other",key,nonce)
        with self.assertRaises(PermissionError):ext.consume_approval("owner",key,"wrong")
        self.assertTrue(store.consume(key,"owner","pending"))
        with self.assertRaises(PermissionError):ext.consume_approval("owner",key,nonce)
    def test_expired_and_mutated_approvals_fail_closed(self):
        result=ext.approval("owner","ai-reader","plan",{"plan_hash":"exact"})
        hidden=result.meta;key=hidden["approval"]["id"];nonce=hidden["approval"]["nonce"]
        row=store.get(key,"owner");row["summary"]["plan_hash"]="changed"
        store.save(key,"owner","pending",{k:v for k,v in row.items() if k not in {"status","job_id","updated_at"}})
        with self.assertRaises(PermissionError):ext.consume_approval("owner",key,nonce)
    def test_widget_handles_current_envelope_legacy_and_no_automatic_execution(self):
        script=ext.APPROVAL_HTML.split("<script>",1)[1].split("</script>",1)[0]
        harness=r"""
const vm=require('node:vm');
(async()=>{
for(const kind of ['flat','mcp_tool_result','call_tool_result']){
 const events={},elements={};let calls=0;
 for(const id of ['plan','approve','status','images'])elements[id]={disabled:true,style:{},textContent:'',addEventListener:(n,f)=>events[id+':'+n]=f,replaceChildren:()=>{},append:()=>{}};
 const hidden={approval:{id:'id',nonce:'nonce'},summary:{count:3},images:['data:image/webp;base64,AAA=']};
 const raw=kind==='flat'?hidden:{[kind]:{_meta:hidden},status:'success'};
 const context={document:{getElementById:id=>elements[id],createElement:()=>({style:{}})},window:{openai:{toolResponseMetadata:raw,callTool:async(name,args)=>{if(args.nonce!=='nonce')throw Error('nonce missing');calls++;return {status:'completed'}}},addEventListener:()=>{}},JSON};
 vm.runInNewContext(process.argv[1],context);
 if(elements.approve.disabled||calls!==0||!elements.plan.textContent.includes('3'))throw Error('hydration failed '+kind);
 await events['approve:click']();await events['approve:click']();
 if(calls!==1||!elements.approve.disabled)throw Error('duplicate or automatic execution '+kind);
}
console.log('widget hydration/explicit click/single-use: passed');
})().catch(e=>{console.error(e.message);process.exit(1)});
"""
        result=subprocess.run(["node","-e",harness,script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    async def test_registered_execution_is_component_only_and_file_contract_complete(self):
        server=FastMCP("test")
        ext.register(server,lambda:SimpleNamespace(subject="owner",admin_user_id=1,scopes=ext.EXTRA_SCOPES))
        tools={t.name:t for t in await server.list_tools()}
        apply=tools["likenovel_execute_approved_expansion"]
        self.assertEqual(apply.meta["ui"]["visibility"],["app"])
        self.assertEqual(apply.meta["openai/visibility"],"private")
        self.assertFalse(apply.annotations.readOnlyHint)
        self.assertTrue({value[0] for value in ext.ACTIONS.values()}.issubset(apply.meta["securitySchemes"][0]["scopes"]))
        schema=tools["likenovel_prepare_banner"].inputSchema
        filedef=schema["$defs"]["ChatGPTFile"]
        self.assertEqual(set(filedef["required"]),{"download_url","file_id"})
        self.assertEqual(set(filedef["properties"]),{"download_url","file_id","mime_type","file_name"})
        self.assertEqual(tools["likenovel_prepare_banner"].meta["openai/fileParams"],["file","mobile_file"])
        self.assertNotIn("record_user_authorization",tools)
    async def test_model_read_scope_cannot_execute_ui_nonce(self):
        server=FastMCP("test")
        ext.register(server,lambda:SimpleNamespace(subject="owner",admin_user_id=1,scopes=[ext.READ_OPERATIONS]))
        result=ext.approval("owner","ai-reader","plan",{"plan_hash":"exact"})
        hidden=result.meta
        with self.assertRaisesRegex(ToolError,"separate expansion scope"):
            await server.call_tool("likenovel_execute_approved_expansion",{"approval_id":hidden["approval"]["id"],"nonce":hidden["approval"]["nonce"]})
        self.assertEqual(store.get(hidden["approval"]["id"],"owner")["status"],"pending")

if __name__=="__main__":unittest.main()
