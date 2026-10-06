import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import { maskResponseSchema, rleDecode } from '../masks';

/** Outlines the objects a result matched (SAM 2.1-tiny masks), drawn over its keyframe. Masks are
 * requested only once the card is on screen (design §10.2: lazy), and a failure just leaves the
 * plain picture.
 */
export function MaskOverlay({ searchId, resultId }) {
  const wrapper = useRef(null);
  const canvas = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = wrapper.current;
    if (!el || typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.4 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const { data } = useQuery({
    queryKey: ['mask', searchId, resultId],
    enabled: visible && Boolean(searchId),
    retry: false,
    staleTime: Infinity,
    queryFn: async () =>
      maskResponseSchema.parse(
        await apiClient.post('/search/grounding', { search_id: searchId, result_id: resultId }),
      ),
  });

  useEffect(() => {
    const el = canvas.current;
    if (!el || !data || data.masks.length === 0) return;
    el.width = data.width;
    el.height = data.height;
    const ctx = el.getContext('2d');
    ctx.clearRect(0, 0, el.width, el.height);
    const accent =
      getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#38bdf8';
    for (const mask of data.masks) {
      const bits = rleDecode(mask.rle);
      const image = ctx.createImageData(el.width, el.height);
      for (let i = 0; i < bits.length; i += 1) {
        if (bits[i]) image.data[i * 4 + 3] = 255;
      }
      // Paint the mask as shape, then colour it: any CSS colour the token holds works.
      const layer = document.createElement('canvas');
      layer.width = el.width;
      layer.height = el.height;
      const lctx = layer.getContext('2d');
      lctx.putImageData(image, 0, 0);
      lctx.globalCompositeOperation = 'source-in';
      lctx.fillStyle = accent;
      lctx.fillRect(0, 0, layer.width, layer.height);
      ctx.globalAlpha = 0.4;
      ctx.drawImage(layer, 0, 0);
    }
    ctx.globalAlpha = 1;
  }, [data]);

  return (
    <div ref={wrapper} className="pointer-events-none absolute inset-0" aria-hidden="true">
      {data && data.masks.length > 0 && (
        <canvas ref={canvas} className="h-full w-full object-cover" />
      )}
    </div>
  );
}
