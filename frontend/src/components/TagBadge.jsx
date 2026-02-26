import React from 'react';
import { Chip } from '@mui/material';

const getNamespaceColor = (namespace) => {
    const map = {
        'language': '#f44336',
        'parody': '#ff9800',
        'character': '#4caf50',
        'group': '#2196f3',
        'artist': '#9c27b0',
        'male': '#795548',
        'female': '#e91e63',
        'misc': '#9e9e9e',
    };
    return map[namespace] || '#9e9e9e';
};

const TagBadge = ({ namespace, value }) => {
    return (
        <Chip
            label={`${namespace}:${value}`}
            size="small"
            sx={{
                bgcolor: getNamespaceColor(namespace),
                color: '#fff',
                mr: 0.5,
                mb: 0.5,
                fontSize: '0.7rem',
                height: 20
            }}
        />
    );
};

export default TagBadge;
