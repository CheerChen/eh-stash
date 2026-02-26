import { useEffect, useRef } from 'react';
import PhotoSwipe from 'photoswipe';
import 'photoswipe/style.css';
import './GalleryLightbox.css';

const NS_ORDER = ['artist', 'group', 'parody', 'character', 'female', 'male', 'language', 'misc', 'other'];

const buildCaption = (g) => {
    if (!g) return '';
    const date = g.posted_at
        ? new Date(g.posted_at).toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
        : '';

    // 按 NS_ORDER 排序，其余命名空间追加到末尾
    const tags = g.tags || {};
    const nsKeys = [
        ...NS_ORDER.filter((ns) => tags[ns]),
        ...Object.keys(tags).filter((ns) => !NS_ORDER.includes(ns)),
    ];

    const tagRows = nsKeys
        .map((ns) => {
            const vals = tags[ns] || [];
            const tagChips = vals
                .map((v) => {
                    const tag = `${ns}:${v}`;
                    const encoded = encodeURIComponent(tag);
                    return `<button type="button" class="pswp-caption-tag" data-tag="${encoded}">${v}</button>`;
                })
                .join('');
            return `<div class="pswp-caption-tagrow"><span class="pswp-caption-ns">${ns}</span>${tagChips}</div>`;
        })
        .join('');

    const exUrl = `https://exhentai.org/g/${g.gid}/${g.token}/`;
    const isAndroid = /Android/i.test(navigator.userAgent);
    const exLink = isAndroid
        ? `intent://exhentai.org/g/${g.gid}/${g.token}/#Intent;scheme=https;S.browser_fallback_url=${encodeURIComponent(exUrl)};end`
        : exUrl;
    const exTarget = isAndroid ? '_self' : '_blank';

    return `
    <div class="pswp__caption-inner">
      <div class="pswp-caption-title">${g.title || ''}</div>
      <div class="pswp-caption-meta">
        <span class="pswp-caption-cat">${g.category || ''}</span>
        <span>⭐ ${g.rating != null ? g.rating.toFixed(2) : '-'}</span>
        <span>❤️ ${g.fav_count ?? '-'}</span>
        <span>💬 ${g.comment_count ?? 0}</span>
        <span>📄 ${g.pages ?? '-'} p</span>
        ${g.language ? `<span>🌐 ${g.language}</span>` : ''}
        ${g.uploader ? `<span>👤 ${g.uploader}</span>` : ''}
        ${date ? `<span>📅 ${date}</span>` : ''}
      </div>
      <div class="pswp-caption-tags">${tagRows}</div>
      <a class="pswp-caption-exlink" href="${exLink}" target="${exTarget}" rel="noopener noreferrer">
        在 ExHentai / EHViewer 中查看 ↗
      </a>
    </div>
  `;
};

export default function GalleryLightbox({ galleries, openIndex, onClose, onTagSearch }) {
    const pswpRef = useRef(null);

    useEffect(() => {
        if (openIndex === null || openIndex === undefined || !galleries?.length) return;

        // Guard: prevent double-init (React StrictMode runs effects twice in dev)
        if (pswpRef.current && !pswpRef.current.isDestroyed) return;

        let isCleanup = false;

        const dataSource = galleries.map((g) => ({
            src: g.gid ? `/v1/thumbs/${g.gid}` : '',
            // 占位尺寸，图片加载后会用 naturalWidth/Height 覆盖
            width: 300,
            height: 420,
            alt: g.title,
            galleryData: g,
        }));

        const pswp = new PhotoSwipe({
            dataSource,
            index: openIndex,
            bgOpacity: 0.92,
            wheelToZoom: true,
            padding: { top: 20, bottom: 20, left: 20, right: 20 },
            showHideAnimationType: 'fade',
        });

        const ensureSlideSize = (slide) => {
            const el = slide?.content?.element;
            if (!(el instanceof HTMLImageElement)) return;

            const applySize = () => {
                if (el.naturalWidth > 0 && el.naturalHeight > 0) {
                    if (slide.data.width !== el.naturalWidth || slide.data.height !== el.naturalHeight) {
                        slide.data.width = el.naturalWidth;
                        slide.data.height = el.naturalHeight;
                        slide.updateContentSize(true);
                        // 当前显示的 slide 需要额外触发全局重布局
                        if (pswp.currSlide === slide) {
                            pswp.updateSize(true);
                        }
                    }
                }
            };

            if (el.complete) {
                applySize();
                return;
            }

            if (!el.dataset.pswpSizeBound) {
                el.dataset.pswpSizeBound = '1';
                el.addEventListener('load', applySize, { once: true });
            }
        };

        // 进入/切换 slide 时校准图片尺寸，修正缩略图的真实宽高比
        pswp.on('change', () => {
            ensureSlideSize(pswp.currSlide);
        });

        // 注册 caption 区域
        pswp.on('uiRegister', () => {
            pswp.ui.registerElement({
                name: 'caption',
                order: 9,
                isButton: false,
                appendTo: 'wrapper',
                html: '',
                onInit: (el) => {
                    el.classList.add('pswp__element--caption');
                    pswp.on('change', () => {
                        el.innerHTML = buildCaption(pswp.currSlide.data.galleryData);
                    });

                    const onCaptionClick = (event) => {
                        const target = event.target;
                        const tagEl = target?.closest?.('.pswp-caption-tag');
                        if (!tagEl) return;
                        const raw = tagEl.getAttribute('data-tag');
                        if (!raw) return;
                        let tag = '';
                        try {
                            tag = decodeURIComponent(raw);
                        } catch {
                            return;
                        }
                        event.preventDefault();
                        event.stopPropagation();
                        if (onTagSearch) {
                            onTagSearch(tag);
                        }
                        if (pswp && !pswp.isDestroyed) {
                            pswp.close();
                        }
                    };

                    el.addEventListener('click', onCaptionClick);
                    pswp.on('destroy', () => {
                        el.removeEventListener('click', onCaptionClick);
                    });
                },
            });
        });

        pswp.on('destroy', () => {
            pswpRef.current = null;
            // 只有用户真实关闭时才触发 onClose，StrictMode cleanup 不触发
            if (!isCleanup) onClose();
        });

        pswp.init();
        pswpRef.current = pswp;

        // 初始化后补一次当前 slide 尺寸
        ensureSlideSize(pswp.currSlide);

        return () => {
            isCleanup = true;
            if (pswpRef.current && !pswpRef.current.isDestroyed) {
                pswpRef.current.destroy();
            }
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [openIndex]);

    return null;
}
