import React from 'react';
import GalleryPage from './pages/GalleryPage';
import { Box, AppBar, Toolbar, Typography, Container } from '@mui/material';

function App() {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <AppBar position="static" color="default" elevation={0} sx={{ borderBottom: '1px solid #333' }}>
        <Toolbar>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1, fontWeight: 'bold' }}>
            EH-Stash
          </Typography>
        </Toolbar>
      </AppBar>
      <Container maxWidth="xl" sx={{ mt: 4, flexGrow: 1 }}>
        <GalleryPage />
      </Container>
    </Box>
  );
}

export default App;
