const BASE = '/v1';

export const fetchGalleries = async (params) => {
  const { tags, ...rest } = params;
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(rest)) {
    if (v !== undefined && v !== null && v !== '') query.append(k, v);
  }
  if (Array.isArray(tags)) {
    for (const t of tags) { if (t) query.append('tag', t); }
  }
  const resp = await fetch(`${BASE}/galleries?${query.toString()}`);
  if (!resp.ok) throw new Error(`Request failed: ${resp.status}`);
  return resp.json();
};

const fetchStats = async () => {
  const resp = await fetch(`${BASE}/stats`);
  if (!resp.ok) throw new Error(`Request failed: ${resp.status}`);
  return resp.json();
};

export const fetchGalleryGroup = async (groupId) => {
  const resp = await fetch(`${BASE}/galleries/group/${groupId}`);
  if (!resp.ok) throw new Error(`Request failed: ${resp.status}`);
  return resp.json();
};
