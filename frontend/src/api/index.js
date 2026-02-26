import axios from 'axios';

const api = axios.create({
  baseURL: '/v1',
});

export const fetchGalleries = async (params) => {
  const { data } = await api.get('/galleries', { params });
  return data;
};

export const fetchStats = async () => {
  const { data } = await api.get('/stats');
  return data;
};
