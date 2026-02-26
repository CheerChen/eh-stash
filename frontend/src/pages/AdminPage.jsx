import React, { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  LinearProgress,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createTask,
  deleteTask,
  getTasks,
  getThumbStats,
  startTask,
  stopTask,
} from '../api/admin';

const TYPE_OPTIONS = [
  { label: 'full', value: 'full' },
  { label: 'incremental', value: 'incremental' },
];

const DEFAULT_FULL = {
  rate_interval: 1,
  inline_set: 'dm_l',
  start_gid: '',
};

const DEFAULT_INCREMENTAL = {
  rate_interval: 1,
  inline_set: 'dm_l',
  detail_quota: 25,
  gid_window: 10000,
  rating_diff_threshold: 0.5,
};

function getDefaultConfig(type) {
  return type === 'full' ? { ...DEFAULT_FULL } : { ...DEFAULT_INCREMENTAL };
}

function buildPayload(form) {
  const base = {
    name: form.name.trim(),
    type: form.type,
    category: form.category.trim(),
  };

  if (form.type === 'full') {
    return {
      ...base,
      config: {
        rate_interval: Number(form.config.rate_interval),
        inline_set: form.config.inline_set,
        start_gid: form.config.start_gid === '' ? null : Number(form.config.start_gid),
      },
    };
  }

  return {
    ...base,
    config: {
      rate_interval: Number(form.config.rate_interval),
      inline_set: form.config.inline_set,
      detail_quota: Number(form.config.detail_quota),
      gid_window: Number(form.config.gid_window),
      rating_diff_threshold: Number(form.config.rating_diff_threshold),
    },
  };
}

export default function AdminPage() {
  const queryClient = useQueryClient();
  const [openCreate, setOpenCreate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [form, setForm] = useState({
    name: '',
    type: 'full',
    category: '',
    config: getDefaultConfig('full'),
  });

  const tasksQuery = useQuery({
    queryKey: ['admin', 'tasks'],
    queryFn: getTasks,
    refetchInterval: 5000,
  });

  const thumbQuery = useQuery({
    queryKey: ['admin', 'thumbStats'],
    queryFn: getThumbStats,
    refetchInterval: 5000,
  });

  const tasks = tasksQuery.data || [];
  const stats = thumbQuery.data || {
    pending: 0,
    processing: 0,
    done: 0,
    failed: 0,
  };

  const loading = tasksQuery.isLoading || thumbQuery.isLoading;

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['admin', 'tasks'] });
    queryClient.invalidateQueries({ queryKey: ['admin', 'thumbStats'] });
  };

  const handleTypeChange = (nextType) => {
    setForm((prev) => ({
      ...prev,
      type: nextType,
      config: getDefaultConfig(nextType),
    }));
  };

  const handleCreate = async () => {
    setErrorMsg('');

    if (!form.name.trim() || !form.category.trim()) {
      setErrorMsg('name 和 category 不能为空');
      return;
    }

    setBusy(true);
    try {
      await createTask(buildPayload(form));
      setOpenCreate(false);
      setForm({
        name: '',
        type: 'full',
        category: '',
        config: getDefaultConfig('full'),
      });
      refresh();
    } catch (err) {
      setErrorMsg(err.message || '创建任务失败');
    } finally {
      setBusy(false);
    }
  };

  const runAction = async (fn) => {
    setErrorMsg('');
    setBusy(true);
    try {
      await fn();
      refresh();
    } catch (err) {
      setErrorMsg(err.message || '操作失败');
    } finally {
      setBusy(false);
    }
  };

  const statusColor = useMemo(
    () => ({
      running: 'success.main',
      stopped: 'text.secondary',
      completed: 'info.main',
      error: 'error.main',
    }),
    []
  );

  return (
    <Stack spacing={2}>
      <Box display="flex" justifyContent="space-between" alignItems="center">
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Admin
        </Typography>
        <Button variant="contained" onClick={() => setOpenCreate(true)} disabled={busy}>
          新建任务
        </Button>
      </Box>

      {errorMsg && <Alert severity="error">{errorMsg}</Alert>}
      {(tasksQuery.isError || thumbQuery.isError) && (
        <Alert severity="error">加载 Admin 数据失败</Alert>
      )}

      <Card variant="outlined">
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Thumb Queue
          </Typography>
          <Grid container spacing={2}>
            <Grid item xs={6} sm={3}>
              <Typography variant="body2" color="text.secondary">pending</Typography>
              <Typography variant="h5">{stats.pending}</Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="body2" color="text.secondary">processing</Typography>
              <Typography variant="h5">{stats.processing}</Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="body2" color="text.secondary">done</Typography>
              <Typography variant="h5">{stats.done}</Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="body2" color="text.secondary">failed</Typography>
              <Typography variant="h5">{stats.failed}</Typography>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Sync Tasks
          </Typography>

          {loading ? (
            <Box display="flex" justifyContent="center" py={3}>
              <CircularProgress size={28} />
            </Box>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>name</TableCell>
                  <TableCell>type</TableCell>
                  <TableCell>category</TableCell>
                  <TableCell>status</TableCell>
                  <TableCell>progress</TableCell>
                  <TableCell align="right">actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {tasks.map((task) => {
                  const progress = Number(task.progress_pct || 0);
                  return (
                    <TableRow key={task.id} hover>
                      <TableCell>{task.name}</TableCell>
                      <TableCell>{task.type}</TableCell>
                      <TableCell>{task.category}</TableCell>
                      <TableCell>
                        <Typography sx={{ color: statusColor[task.status] || 'text.secondary' }}>
                          {task.status}
                        </Typography>
                      </TableCell>
                      <TableCell sx={{ minWidth: 170 }}>
                        <Box display="flex" alignItems="center" gap={1}>
                          <Box sx={{ width: 120 }}>
                            <LinearProgress variant="determinate" value={Math.max(0, Math.min(100, progress))} />
                          </Box>
                          <Typography variant="body2">{progress.toFixed(1)}%</Typography>
                        </Box>
                      </TableCell>
                      <TableCell align="right">
                        <Stack direction="row" spacing={1} justifyContent="flex-end">
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => runAction(() => startTask(task.id))}
                            disabled={busy}
                          >
                            Start
                          </Button>
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => runAction(() => stopTask(task.id))}
                            disabled={busy}
                          >
                            Stop
                          </Button>
                          <Button
                            size="small"
                            color="error"
                            variant="outlined"
                            onClick={() => runAction(() => deleteTask(task.id))}
                            disabled={busy}
                          >
                            Delete
                          </Button>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  );
                })}

                {tasks.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6}>
                      <Typography color="text.secondary">暂无任务</Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={openCreate} onClose={() => setOpenCreate(false)} fullWidth maxWidth="sm">
        <DialogTitle>新建同步任务</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="name"
              value={form.name}
              onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
              fullWidth
            />

            <TextField
              select
              label="type"
              value={form.type}
              onChange={(e) => handleTypeChange(e.target.value)}
              fullWidth
            >
              {TYPE_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              label="category"
              value={form.category}
              onChange={(e) => setForm((prev) => ({ ...prev, category: e.target.value }))}
              fullWidth
            />

            <TextField
              label="rate_interval"
              type="number"
              inputProps={{ step: '0.1' }}
              value={form.config.rate_interval}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  config: { ...prev.config, rate_interval: e.target.value },
                }))
              }
              fullWidth
            />

            <TextField
              label="inline_set"
              value={form.config.inline_set}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  config: { ...prev.config, inline_set: e.target.value },
                }))
              }
              fullWidth
            />

            {form.type === 'full' ? (
              <TextField
                label="start_gid (optional)"
                type="number"
                value={form.config.start_gid}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    config: { ...prev.config, start_gid: e.target.value },
                  }))
                }
                fullWidth
              />
            ) : (
              <>
                <TextField
                  label="detail_quota"
                  type="number"
                  value={form.config.detail_quota}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      config: { ...prev.config, detail_quota: e.target.value },
                    }))
                  }
                  fullWidth
                />
                <TextField
                  label="gid_window"
                  type="number"
                  value={form.config.gid_window}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      config: { ...prev.config, gid_window: e.target.value },
                    }))
                  }
                  fullWidth
                />
                <TextField
                  label="rating_diff_threshold"
                  type="number"
                  inputProps={{ step: '0.1' }}
                  value={form.config.rating_diff_threshold}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      config: {
                        ...prev.config,
                        rating_diff_threshold: e.target.value,
                      },
                    }))
                  }
                  fullWidth
                />
              </>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenCreate(false)} disabled={busy}>取消</Button>
          <Button onClick={handleCreate} variant="contained" disabled={busy}>创建</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
