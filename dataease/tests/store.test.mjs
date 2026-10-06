// The shared helpers of the DataEase scripts, without DataEase: the tree walk and the password change
// (lib/dataease-client.mjs), saving and publishing a dashboard (lib/dashboard-store.mjs), the dataset fields
// (seed-dashboards.mjs) and which nodes are ours (lib/languages.mjs, translate-dashboards.mjs). Plain Node 24.
//   docker run --rm --network none -v <repo>/dataease:/d -w /d node:24-alpine node --test tests/*.test.mjs
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { test } from 'node:test';
import { DEFAULT_PASSWORD, changePassword, encryptFor, flattenTree } from '../lib/dataease-client.mjs';
import {
  DATAEASE_VERSION, createFolder, dashboardNodes, dashboardState, deleteDashboard, encodeCalculatedFields, findDashboard, saveAndPublish,
} from '../lib/dashboard-store.mjs';
import { isCopyOf } from '../lib/languages.mjs';
import { datasetFields, withDashboardKeys } from '../seed-dashboards.mjs';
import { isEnglishDashboard, isLanguageFolder } from '../translate-dashboards.mjs';

// A stand-in for a signed-in DataEase: it writes down every call and answers from a list.
function fakeDataEase(answers = {}) {
  const calls = [];
  return {
    calls,
    async post(path, body) { calls.push({ path, body }); return answers[path]; },
    async raw(path, options = {}) { calls.push({ path, body: options.body, raw: true }); return answers[path]; },
  };
}

const TREE = [{ id: '0', name: 'root', leaf: false, children: [
  { id: '1150000000000000000', name: 'Mission', leaf: false, children: [
    { id: '1150001000000000000', name: 'Key indicators', leaf: true },
    { id: '1150100000000000000', name: 'Deutsch', leaf: false, children: [{ id: '1150101010000000000', name: 'Kennzahlen', leaf: true }] },
    { id: '1302280795569917952', name: 'Made by hand', leaf: true },
  ] },
] }];

test('flattenTree lists every node once, the children after their folder', () => {
  assert.deepEqual(flattenTree(TREE).map(n => n.name), ['root', 'Mission', 'Key indicators', 'Deutsch', 'Kennzahlen', 'Made by hand']);
  assert.deepEqual(flattenTree(undefined), []);
  assert.deepEqual(flattenTree([{ id: 1 }]), [{ id: 1 }]);
});

test('the password change sends both passwords encrypted with DataEase\'s key, never as plain text', async () => {
  const { publicKey, privateKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 1024 });
  const pem = publicKey.export({ type: 'spki', format: 'pem' });
  const de = { ...fakeDataEase(), async publicKey() { return pem; } };
  await changePassword(de, DEFAULT_PASSWORD, 'New-Secret9');
  assert.equal(de.calls.length, 1);
  assert.equal(de.calls[0].path, '/user/modifyPwd');
  const decrypt = text => crypto.privateDecrypt({ key: privateKey, padding: crypto.constants.RSA_PKCS1_PADDING }, Buffer.from(text, 'base64')).toString('utf8');
  assert.equal(decrypt(de.calls[0].body.pwd), 'DataEase@123456');
  assert.equal(decrypt(de.calls[0].body.newPwd), 'New-Secret9');
  assert.ok(!JSON.stringify(de.calls).includes('New-Secret9'), 'no plain password in the request');
  assert.equal(decrypt(encryptFor(pem, 'ä-ö')), 'ä-ö', 'umlauts survive');
});

const DASHBOARD = {
  id: '1150001000000000000', name: 'Key indicators', canvasStyleData: { width: 1280 }, componentData: [{ id: 'c1' }],
  canvasViewInfo: { v1: { id: 'v1', yAxis: [{ extField: 2, originName: '[1] * 100' }, { extField: 0, originName: 'weeks' }] } },
};

test('a new dashboard is created empty, then saved with its charts, then published', async () => {
  const de = fakeDataEase();
  await saveAndPublish(de, DASHBOARD, { folderId: '1150000000000000000', exists: false });
  assert.deepEqual(de.calls.map(c => c.path), ['/dataVisualization/saveCanvas', '/dataVisualization/updateCanvas', '/dataVisualization/updatePublishStatus']);
  const [create, save, publish] = de.calls.map(c => c.body);
  assert.deepEqual(create.canvasViewInfo, {});
  for (const body of [create, save]) {
    assert.equal(body.pid, '1150000000000000000');
    assert.equal(body.nodeType, 'leaf');
    assert.equal(body.mobileLayout, true, 'the phone layout is on unless the dashboard says otherwise');
    assert.equal(body.checkVersion, DATAEASE_VERSION);
    assert.equal(body.canvasStyleData, '{"width":1280}', 'the canvas as JSON text');
    assert.equal(body.componentData, '[{"id":"c1"}]');
  }
  assert.equal(save.canvasViewInfo.v1.yAxis[0].originName, Buffer.from('[1] * 100').toString('base64'), 'a formula goes Base64-encoded');
  assert.equal(save.canvasViewInfo.v1.yAxis[1].originName, 'weeks', 'a plain column does not');
  assert.equal(DASHBOARD.canvasViewInfo.v1.yAxis[0].originName, '[1] * 100', 'the dashboard itself is not changed');
  assert.deepEqual(publish, { id: DASHBOARD.id, name: 'Key indicators', type: 'dashboard', busiFlag: 'dashboard', status: 1, mobileLayout: true, activeViewIds: ['v1'] });
});

test('an existing dashboard is only saved and published; a copy without a phone layout keeps it off', async () => {
  const de = fakeDataEase();
  await saveAndPublish(de, { ...DASHBOARD, mobileLayout: false }, { folderId: 'f', exists: true });
  assert.deepEqual(de.calls.map(c => c.path), ['/dataVisualization/updateCanvas', '/dataVisualization/updatePublishStatus']);
  assert.equal(de.calls[0].body.mobileLayout, false);
  assert.equal(de.calls[1].body.mobileLayout, false);
});

test('encodeCalculatedFields encodes the formulas of every field list that can hold one', () => {
  const views = { v: { xAxis: [{ extField: 2, originName: 'a' }], extColor: [{ extField: 2, originName: 'b' }], drillFields: [{ extField: 2, originName: 'c' }] } };
  const encoded = encodeCalculatedFields(views);
  assert.equal(encoded.v.xAxis[0].originName, 'YQ==');
  assert.equal(encoded.v.extColor[0].originName, 'Yg==');
  assert.equal(encoded.v.drillFields[0].originName, 'c', 'drill-down fields are sent as they are');
});

test('dashboardState: free, live or deleted, from DataEase\'s two answers', async () => {
  const id = '1150001000000000000';
  const type = `/dataVisualization/findDvType/${id}`;
  assert.equal(await dashboardState(fakeDataEase({ [type]: { status: 200, json: { code: 500 } } }), id), 'free');
  const live = fakeDataEase({ [type]: { status: 200, json: { code: 0 } }, '/dataVisualization/findById': { json: { code: 0, data: { id } } } });
  assert.equal(await dashboardState(live, id), 'live');
  assert.deepEqual(live.calls[1].body, { id, busiFlag: 'dashboard', source: 'main' });
  assert.equal(await dashboardState(fakeDataEase({ [type]: { status: 200, json: { code: 0 } }, '/dataVisualization/findById': { json: { code: 0, data: null } } }), id), 'deleted');
  await assert.rejects(dashboardState(fakeDataEase({ [type]: { status: 502, json: null } }), id), /did not answer/);
});

test('the other calls: the dashboard tree, one dashboard, a folder, a delete', async () => {
  const de = fakeDataEase({ '/dataVisualization/tree': TREE });
  assert.equal((await dashboardNodes(de)).length, 6);
  await findDashboard(de, '11');
  await createFolder(de, { id: '1150100000000000000', name: 'Deutsch', parentId: '1150000000000000000' });
  await deleteDashboard(de, '12');
  assert.deepEqual(de.calls.slice(1), [
    { path: '/dataVisualization/findById', body: { id: '11', busiFlag: 'dashboard', resourceTable: 'core', source: 'main' } },
    { path: '/dataVisualization/saveCanvas', body: { id: '1150100000000000000', name: 'Deutsch', pid: '1150000000000000000', nodeType: 'folder', type: 'dashboard' } },
    { path: '/dataVisualization/deleteLogic/12/dashboard', body: undefined },
  ]);
});

test('dataset fields: labelled columns, then calculated fields that name columns by field id', () => {
  const spec = { key: 'kpi-weeks', index: 2, labels: { zone: 'Zone' },
    calculated: [{ name: 'pct', label: 'Percent', expression: 'SUM([done]) * 100 / SUM([goal])', deType: 3 }, { name: 'who', label: 'Who', expression: '[zone]', deType: 0 }] };
  const fields = datasetFields(spec, [{ originName: 'zone' }, { originName: 'done' }, { originName: 'goal' }], 'ds', 'tbl');
  assert.deepEqual(fields.slice(0, 3).map(f => [f.name, f.description, f.datasourceId, f.datasetTableId]),
    [['Zone', 'zone', 'ds', 'tbl'], ['done', 'done', 'ds', 'tbl'], ['goal', 'goal', 'ds', 'tbl']]);
  const [pct, who] = fields.slice(3);
  assert.equal(Buffer.from(pct.originName, 'base64').toString(), `SUM([${fields[1].id}]) * 100 / SUM([${fields[2].id}])`);
  assert.deepEqual([pct.groupType, pct.type, pct.extField, who.groupType, who.type], ['q', 'DOUBLE', 2, 'd', 'VARCHAR']);
  assert.throws(() => datasetFields({ ...spec, calculated: [{ name: 'x', expression: '[nothing]' }] }, [], 'ds', 'tbl'), /unknown column nothing/);

  const saved = withDashboardKeys(spec, [...fields.slice(0, 3), { ...pct, id: Number(pct.id) }, who]);
  assert.deepEqual(saved.map(f => f.gfmKey), ['zone', 'done', 'goal', 'pct', 'who']);
  assert.equal(saved[3].originName, `SUM([${fields[1].id}]) * 100 / SUM([${fields[2].id}])`, 'the formula is back as text');
  assert.equal(saved[3].gfmAgg, true, 'a formula that adds up rows');
  assert.equal(saved[4].gfmAgg, undefined);
});

test('which nodes are ours: English dashboards, language folders, copies', () => {
  const nodes = flattenTree(TREE);
  assert.deepEqual(nodes.filter(isEnglishDashboard).map(n => n.name), ['Key indicators']);
  assert.deepEqual(nodes.filter(isLanguageFolder).map(n => n.name), ['Deutsch']);
  assert.deepEqual(nodes.filter(n => isCopyOf(n, 1, 1)).map(n => n.name), ['Kennzahlen'], 'any generation of the German copy');
  assert.deepEqual(nodes.filter(n => isCopyOf(n, 2, 1)), [], 'no Spanish copy yet');
  assert.equal(isCopyOf({ id: '1150101000000000000', leaf: false }, 1, 1), false, 'a folder is not a copy');
});
