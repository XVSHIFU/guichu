import assert from 'node:assert/strict';
import {trajectorySteps,trajectoryTimeline,recordedDuration} from '../src/trajectory.js';
const events=[{seq:1,type:'started'},
 {seq:2,type:'tool_started',name:'get_object',at:'2026-10-03T00:00:00Z'},
 {seq:3,type:'tool_finished',name:'get_object',ok:true,at:'2026-10-03T00:00:00.125Z'},
 {seq:4,type:'tool_started',name:'get_object'},
 {seq:5,type:'tool_finished',name:'get_object',ok:false},
 {seq:6,type:'text',text:'first '},{seq:7,type:'text',text:'answer'},
 {seq:8,type:'tool_finished',name:'orphan'},
 {seq:9,type:'tool_started',name:'pending'},
 {seq:10,type:'finished',status:'cancelled'}];
const steps=trajectorySteps([...events,events[2]].reverse(),'cancelled');
assert.equal(steps.length,7);
assert.deepEqual(steps[1].events.map(e=>e.seq),[2,3]);
assert.equal(steps[1].label,'已完成');
assert.equal(steps[2].label,'调用失败');
assert.equal(steps[3].text,'first answer');
assert.equal(steps[4].start,undefined);
assert.equal(steps[4].label,'已返回，状态未记录');
assert.equal(steps[5].label,'未记录完成结果');
assert.equal(trajectorySteps([{seq:1,type:'tool_started',name:'get_object'}],'running')[0].label,'正在调用');
assert.equal(recordedDuration(steps[1].start,steps[1].end),'125 毫秒');
assert.equal(recordedDuration(null,'2026-10-03'),null);
assert.equal(recordedDuration('bad','bad'),null);
assert.equal(recordedDuration('2026-10-04','2026-10-03'),null);
const timed=trajectoryTimeline(steps,true);assert.equal(timed.length,1);assert.equal(timed[0].id,2);assert.equal(timed[0].width,100);
assert.equal(trajectoryTimeline(steps,false).length,7);
assert.deepEqual(trajectoryTimeline([{id:1,kind:'tool'}],true),[]);
console.log('PASS trajectory pairing/repeated tools/duplicates/orphan results/text aggregation/pending interruption/no invented duration');
