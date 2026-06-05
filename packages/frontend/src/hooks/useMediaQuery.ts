import { useState, useEffect } from 'react';

/**
 * 响应式媒体查询 Hook
 * 用法：const isMobile = useMediaQuery('(max-width: 767px)');
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window !== 'undefined') {
      return window.matchMedia(query).matches;
    }
    return false;
  });

  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener('change', handler);
    // 修正初始化值（SSR/预渲染场景下可能不准确）
    setMatches(mql.matches);
    return () => mql.removeEventListener('change', handler);
  }, [query]);

  return matches;
}
