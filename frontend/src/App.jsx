import React from 'react';
import GalleryPage from './pages/GalleryPage';
import AdminPage from './pages/AdminPage';
import { Box, AppBar, Toolbar, Typography, Container, Button, Stack } from '@mui/material';
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom';

function App() {
  return (
    <BrowserRouter>
      <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <AppBar position="static" color="default" elevation={0} sx={{ borderBottom: '1px solid #333' }}>
          <Toolbar>
            <Typography variant="h6" component="div" sx={{ flexGrow: 1, fontWeight: 'bold' }}>
              EH-Stash
            </Typography>
            <Stack direction="row" spacing={1}>
              <Button
                component={NavLink}
                to="/"
                color="inherit"
                sx={{ '&.active': { textDecoration: 'underline' } }}
              >
                Gallery
              </Button>
              <Button
                component={NavLink}
                to="/admin"
                color="inherit"
                sx={{ '&.active': { textDecoration: 'underline' } }}
              >
                Admin
              </Button>
            </Stack>
          </Toolbar>
        </AppBar>
        <Container maxWidth="xl" sx={{ mt: 4, flexGrow: 1 }}>
          <Routes>
            <Route path="/" element={<GalleryPage />} />
            <Route path="/admin" element={<AdminPage />} />
          </Routes>
        </Container>
      </Box>
    </BrowserRouter>
  );
}

export default App;
