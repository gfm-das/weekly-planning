// Reading and saving dashboards through DataEase's web API. Shared by seed-dashboards.mjs (the three English
// dashboards) and translate-dashboards.mjs (their copies in 13 languages). Plain Node 24, no packages.
// "de" is a signed-in DataEase from lib/dataease-client.mjs (the tests use a stand-in with the same post/raw).
import { flattenTree } from './dataease-client.mjs';

/** The DataEase version the saved dashboards are written for (dataease/compose.yml pins the same image). */
export const DATAEASE_VERSION = '2.10.27';

/** How many times a dashboard may be deleted in DataEase and made again (see "generations" in seed-dashboards.mjs). */
export const MAX_GENERATIONS = 90;

// The field lists of a chart that can hold a calculated field.
const CALCULATED_FIELD_LISTS = ['xAxis', 'xAxisExt', 'yAxis', 'yAxisExt', 'extBubble', 'extLabel', 'extStack', 'extTooltip', 'extColor'];

/** Every dashboard and folder of DataEase's dashboard tree, as one flat list. */
export async function dashboardNodes(de) {
  return flattenTree(await de.post('/dataVisualization/tree', { busiFlag: 'dashboard' }));
}

/** One dashboard as DataEase keeps it, with its charts (canvasViewInfo). */
export function findDashboard(de, id) {
  return de.post('/dataVisualization/findById', { id, busiFlag: 'dashboard', resourceTable: 'core', source: 'main' });
}

/** 'free' (the id was never used), 'live' (a dashboard that is not deleted) or 'deleted'. */
export async function dashboardState(de, id) {
  const type = await de.raw(`/dataVisualization/findDvType/${id}`);
  if (type.status === 200 && type.json && type.json.code !== 0) return 'free';
  if (type.status !== 200 || !type.json) throw new Error(`DataEase did not answer about dashboard ${id}.`);
  const found = await de.raw('/dataVisualization/findById', { method: 'POST', body: { id, busiFlag: 'dashboard', source: 'main' } });
  return found.json?.code === 0 && found.json.data?.id ? 'live' : 'deleted';
}

/** DataEase expects the formulas of calculated fields Base64-encoded when a dashboard is saved (its api/visualization). */
export function encodeCalculatedFields(views) {
  const copy = JSON.parse(JSON.stringify(views));
  for (const view of Object.values(copy)) {
    for (const list of CALCULATED_FIELD_LISTS) {
      for (const field of view[list] || []) {
        if (field.extField === 2) field.originName = Buffer.from(field.originName, 'utf8').toString('base64');
      }
    }
  }
  return copy;
}

/**
 * Saves a dashboard into a folder and publishes it; a new one (exists: false) is first created empty.
 * dashboard: { id, name, canvasStyleData, componentData, canvasViewInfo, mobileLayout (true when left out) }.
 */
export async function saveAndPublish(de, dashboard, { folderId, exists }) {
  const mobileLayout = dashboard.mobileLayout !== false;
  const common = {
    id: dashboard.id, name: dashboard.name, pid: folderId, type: 'dashboard', nodeType: 'leaf', mobileLayout,
    canvasStyleData: JSON.stringify(dashboard.canvasStyleData), componentData: JSON.stringify(dashboard.componentData),
    selfWatermarkStatus: false, checkVersion: DATAEASE_VERSION, contentId: String(Date.now()), watermarkInfo: null, version: 3,
  };
  if (!exists) await de.post('/dataVisualization/saveCanvas', { ...common, canvasViewInfo: {} });
  await de.post('/dataVisualization/updateCanvas', { ...common, canvasViewInfo: encodeCalculatedFields(dashboard.canvasViewInfo) });
  await de.post('/dataVisualization/updatePublishStatus', {
    id: dashboard.id, name: dashboard.name, type: 'dashboard', busiFlag: 'dashboard', status: 1, mobileLayout,
    activeViewIds: Object.keys(dashboard.canvasViewInfo),
  });
}

/** Makes a dashboard folder with a fixed id. */
export function createFolder(de, { id, name, parentId }) {
  return de.post('/dataVisualization/saveCanvas', { id, name, pid: parentId, nodeType: 'folder', type: 'dashboard' });
}

/** Deletes a dashboard or folder. DataEase only marks it deleted, so its id can never be used again. */
export function deleteDashboard(de, id) {
  return de.post(`/dataVisualization/deleteLogic/${id}/dashboard`);
}
