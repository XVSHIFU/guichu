"""Deterministic Agent acceptance suite; does not call paid model services."""
import json
from pathlib import Path
import sys
import time
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'app/tests')]
CASES={
 '连接错误与流中断':'test_model_provider.ModelProviderTests.test_redirect_errors_and_truncation_are_safe',
 '实时配置检查':'test_agent_runtime.AgentRuntimeTests.test_real_directory_measurement_and_live_config_check',
 '批量分类确认与恢复':'test_extended_agent.ExtendedAgentTests.test_batch_chat_proposal_confirm_restore_and_scope',
 '配置冲突与重启不重放':'test_agent_runtime.AgentRuntimeTests.test_conflict_reject_and_restart_never_replay',
 '额度耗尽仍返回已知结果':'test_agent_runtime.AgentRuntimeTests.test_budget_exhaustion_preserves_results_and_reserves_summary',
 '取消后保留终态':'test_assistant_runtime.AssistantRuntimeTests.test_cancel_persists_terminal_state_and_clears_session_activity',
}
def main():
 results=[]
 for name,test in CASES.items():
  start=time.monotonic();out=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromName(test))
  results.append({'scenario':name,'test':test,'passed':out.wasSuccessful(),'seconds':round(time.monotonic()-start,3),'failures':[text for _,text in out.failures+out.errors]})
 target=ROOT/'app/test-results/agent-acceptance.json';target.parent.mkdir(exist_ok=True)
 target.write_text(json.dumps({'kind':'deterministic runtime acceptance; not model quality scoring','cases':results},ensure_ascii=False,indent=2),encoding='utf-8')
 print(target);return 0 if all(r['passed'] for r in results) else 1
if __name__=='__main__':raise SystemExit(main())
