import React from 'react';
import { Paper, Stack, TextField, MenuItem, Slider, Typography, FormControl, InputLabel, Select, Box } from '@mui/material';

const FilterPanel = ({ filters, onChange, tagInputRef }) => {
  const handleChange = (field) => (event) => {
    onChange({ ...filters, [field]: event.target.value });
  };

  const handleSliderChange = (field) => (event, newValue) => {
    onChange({ ...filters, [field]: newValue });
  };

  return (
    <Paper sx={{ p: 2, mb: 3 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={3} alignItems="center">
        <FormControl size="small" sx={{ minWidth: 120 }}>
          <InputLabel>Category</InputLabel>
          <Select
            value={filters.category || ''}
            label="Category"
            onChange={handleChange('category')}
          >
            <MenuItem value="">All</MenuItem>
            <MenuItem value="Manga">Manga</MenuItem>
            <MenuItem value="Doujinshi">Doujinshi</MenuItem>
            <MenuItem value="Cosplay">Cosplay</MenuItem>
            <MenuItem value="Asian Porn">Asian Porn</MenuItem>
            <MenuItem value="Non-H">Non-H</MenuItem>
            <MenuItem value="Western">Western</MenuItem>
            <MenuItem value="Image Set">Image Set</MenuItem>
            <MenuItem value="Game CG">Game CG</MenuItem>
            <MenuItem value="Artist CG">Artist CG</MenuItem>
            <MenuItem value="Misc">Misc</MenuItem>
          </Select>
        </FormControl>

        <FormControl size="small" sx={{ minWidth: 120 }}>
          <InputLabel>Sort By</InputLabel>
          <Select
            value={filters.sort || 'fav_count'}
            label="Sort By"
            onChange={handleChange('sort')}
          >
            <MenuItem value="fav_count">Favorites</MenuItem>
            <MenuItem value="rating">Rating</MenuItem>
            <MenuItem value="comment_count">Comments</MenuItem>
            <MenuItem value="posted_at">Posted Date</MenuItem>
          </Select>
        </FormControl>

        <Box sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Typography variant="caption">Search Tag (namespace:value)</Typography>
          <Box
            component="input"
            ref={tagInputRef}
            value={filters.tag || ''}
            onChange={handleChange('tag')}
            placeholder="language:chinese"
            sx={{
              height: 32,
              px: 1,
              borderRadius: 1,
              border: '1px solid rgba(0,0,0,0.23)',
              bgcolor: '#fff',
              fontSize: 14,
              outline: 'none',
              '&:focus': {
                borderColor: 'primary.main',
                boxShadow: '0 0 0 2px rgba(25, 118, 210, 0.2)',
              },
            }}
          />
        </Box>

        <Box sx={{ width: 150 }}>
          <Typography variant="caption" gutterBottom>Min Rating: {filters.min_rating}</Typography>
          <Slider
            value={filters.min_rating || 0}
            onChange={handleSliderChange('min_rating')}
            step={0.5}
            marks
            min={0}
            max={5}
            size="small"
          />
        </Box>

        <Box sx={{ width: 150 }}>
          <Typography variant="caption" gutterBottom>Min Favorites: {filters.min_fav}</Typography>
          <TextField
            type="number"
            variant="standard"
            size="small"
            value={filters.min_fav || 0}
            onChange={handleChange('min_fav')}
            InputProps={{ inputProps: { min: 0 } }}
          />
        </Box>
      </Stack>
    </Paper>
  );
};

export default FilterPanel;
