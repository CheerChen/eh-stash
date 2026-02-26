import React, { useState, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Grid, Pagination, Box, CircularProgress, Typography, Alert } from '@mui/material';
import { fetchGalleries } from '../api';
import GalleryCard from '../components/GalleryCard';
import FilterPanel from '../components/FilterPanel';
import GalleryLightbox from '../components/GalleryLightbox';

const PAGE_SIZE = 100;

const GalleryPage = () => {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    category: '',
    sort: 'fav_count',
    min_rating: 0,
    min_fav: 0,
    tag: '',
    language: '',
  });
  const [openIndex, setOpenIndex] = useState(null);
  const tagInputRef = useRef(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['galleries', page, filters],
    queryFn: () => {
      // sort 由前端本地处理，不传给 API
      const { sort, ...apiFilters } = filters;
      return fetchGalleries({ page, page_size: PAGE_SIZE, sort: 'gid_desc', ...apiFilters });
    },
    keepPreviousData: true,
  });

  const handleFilterChange = (newFilters) => {
    setFilters(newFilters);
    setPage(1);
  };

  const handleTagSearch = (tag) => {
    if (!tag) return;
    setFilters((prev) => ({ ...prev, tag }));
    setPage(1);
    requestAnimationFrame(() => {
      tagInputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      tagInputRef.current?.focus();
    });
  };

  const handlePageChange = (event, value) => {
    setPage(value);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  if (isError) {
    return <Alert severity="error">Error fetching galleries: {error.message}</Alert>;
  }

  const rawItems = data?.items || [];
  const totalPages = data?.pages || 1;
  const total = data?.total ?? 0;
  const pageSize = data?.size ?? PAGE_SIZE;

  // 前端对当前页本地排序
  const SORT_FNS = {
    fav_count: (a, b) => (b.fav_count ?? 0) - (a.fav_count ?? 0),
    rating: (a, b) => (b.rating ?? 0) - (a.rating ?? 0),
    comment_count: (a, b) => (b.comment_count ?? 0) - (a.comment_count ?? 0),
    posted_at: (a, b) => new Date(b.posted_at ?? 0) - new Date(a.posted_at ?? 0),
  };
  const items = [...rawItems].sort(SORT_FNS[filters.sort] ?? SORT_FNS.fav_count);

  return (
    <Box>
      <FilterPanel filters={filters} onChange={handleFilterChange} tagInputRef={tagInputRef} />

      {isLoading ? (
        <Box display="flex" justifyContent="center" my={5}>
          <CircularProgress />
        </Box>
      ) : (
        <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            共 {total} 条结果（第 {page} / {totalPages} 页，每页 {pageSize} 条）
          </Typography>

          <Grid container spacing={2}>
            {items.map((gallery, idx) => (
              <Grid item key={gallery.gid} xs={6} sm={4} md={3} lg={2}>
                <GalleryCard
                  gallery={gallery}
                  onOpen={() => setOpenIndex(idx)}
                />
              </Grid>
            ))}
          </Grid>

          <Box display="flex" justifyContent="center" my={4}>
            <Pagination
              count={totalPages}
              page={page}
              onChange={handlePageChange}
              color="primary"
              showFirstButton
              showLastButton
            />
          </Box>
        </>
      )}

      {openIndex !== null && (
        <GalleryLightbox
          galleries={items}
          openIndex={openIndex}
          onClose={() => setOpenIndex(null)}
          onTagSearch={handleTagSearch}
        />
      )}
    </Box>
  );
};

export default GalleryPage;
