import {spawnSync} from 'node:child_process';
const suites={core:['onboarding','assistant-production','agent-process','extended-proposals','model-catalog','theme-gallery'],all:['onboarding','assistant-production','agent-process','extended-proposals','model-catalog','theme-gallery','assistant-workspace','assistant-trajectory','assistant-run-history','assistant-resize','actions','mcp-actions','directories','themes']};
const name=process.argv[2]||'core';if(!suites[name])throw Error('Use core or all');
for(const test of suites[name]){console.log(`Running ${test}`);const result=spawnSync(process.execPath,[`tests/${test}.mjs`],{stdio:'inherit'});if(result.status!==0)process.exit(result.status||1)}
