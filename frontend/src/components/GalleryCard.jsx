import React from 'react';
import { Card, CardActionArea, CardContent, CardMedia, Typography, Box, Chip, Stack, IconButton, Tooltip } from '@mui/material';
import StarIcon from '@mui/icons-material/Star';
import FavoriteIcon from '@mui/icons-material/Favorite';
import ChatBubbleOutlineIcon from '@mui/icons-material/ChatBubbleOutline';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';

const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
const isAndroid = /Android/i.test(navigator.userAgent);

// Android 用 intent:// 直接唤起 EHViewer，不依赖"默认应用"设置
const getExUrl = (gid, token) => {
  const https = `https://exhentai.org/g/${gid}/${token}/`;
  if (isAndroid) {
    const fallback = encodeURIComponent(https);
    return `intent://exhentai.org/g/${gid}/${token}/#Intent;scheme=https;S.browser_fallback_url=${fallback};end`;
  }
  return https;
};

const getCategoryColor = (category) => {
  const map = {
    'Manga': '#ff9800', // Orange
    'Doujinshi': '#f44336', // Red
    'Cosplay': '#9c27b0', // Purple
    'Asian Porn': '#e91e63', // Pink
    'Non-H': '#2196f3', // Blue
    'Western': '#4caf50', // Green
    'Image Set': '#3f51b5', // Indigo
    'Game CG': '#009688', // Teal
    'Artist CG': '#ffeb3b', // Yellow
    'Misc': '#9e9e9e', // Grey
  };
  return map[category] || '#9e9e9e';
};

const FALLBACK_IMAGE = `data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='280' viewBox='0 0 200 280'><rect width='200' height='280' fill='%23333'/><text x='100' y='145' font-family='sans-serif' font-size='14' fill='%23888' text-anchor='middle'>No Cover</text></svg>`;

const GalleryCard = ({ gallery, onOpen }) => {
  const { gid, token, title, category, rating, fav_count, comment_count, thumb, posted_at, uploader } = gallery;
  const exUrl = getExUrl(gid, token);

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', position: 'relative' }}>
      <CardActionArea
        onClick={onOpen}
        sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column', alignItems: 'stretch' }}
      >
        <Box sx={{ position: 'relative', pt: '140%', bgcolor: '#111' }}>
          <CardMedia
            component="img"
            image={thumb ? `/v1/thumbs/${gid}` : FALLBACK_IMAGE}
            alt={title}
            onError={(e) => { e.target.onerror = null; e.target.src = FALLBACK_IMAGE; }}
            sx={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
              objectFit: 'contain',
            }}
          />
          <Chip
            label={category}
            size="small"
            sx={{
              position: 'absolute',
              top: 8,
              right: 8,
              bgcolor: getCategoryColor(category),
              color: '#fff',
              fontWeight: 'bold',
              fontSize: '0.7rem'
            }}
          />
        </Box>
        <CardContent sx={{ flexGrow: 1, p: 1.5 }}>
          <Typography
            variant="subtitle2"
            component="div"
            sx={{
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              mb: 1,
              lineHeight: 1.2,
              fontWeight: 500
            }}
            title={title}
          >
            {title}
          </Typography>

          <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 'auto', color: 'text.secondary', fontSize: '0.8rem' }}>
            <Box display="flex" alignItems="center">
              <StarIcon sx={{ fontSize: 14, color: '#ffb300', mr: 0.5 }} />
              {rating?.toFixed(1)}
            </Box>
            <Box display="flex" alignItems="center">
              <FavoriteIcon sx={{ fontSize: 14, color: '#f44336', mr: 0.5 }} />
              {fav_count}
            </Box>
            {comment_count > 0 && (
              <Box display="flex" alignItems="center">
                <ChatBubbleOutlineIcon sx={{ fontSize: 14, color: '#78909c', mr: 0.5 }} />
                {comment_count}
              </Box>
            )}
          </Stack>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            {uploader}
          </Typography>
        </CardContent>
      </CardActionArea>
      <Tooltip title="在 ExHentai 打开" placement="top">
        <IconButton
          size="medium"
          component="a"
          href={exUrl}
          target={isAndroid ? '_self' : '_blank'}
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          sx={{
            position: 'absolute',
            bottom: 4,
            right: 4,
            bgcolor: 'rgba(0,0,0,0.5)',
            color: '#fff',
            width: { xs: 40, sm: 32 },
            height: { xs: 40, sm: 32 },
            '&:hover': { bgcolor: 'rgba(0,0,0,0.8)' },
          }}
        >
          <OpenInNewIcon sx={{ fontSize: { xs: 20, sm: 16 } }} />
        </IconButton>
      </Tooltip>
    </Card>
  );
};

export default GalleryCard;
