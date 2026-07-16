const DASHBOARD_FALLBACK = '/dashboard';

export function getSafeDashboardRedirect(value: string | null | undefined): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) {
    return DASHBOARD_FALLBACK;
  }

  try {
    const parsed = new URL(value, 'https://portal.local');
    const isDashboardPath = parsed.pathname === DASHBOARD_FALLBACK
      || parsed.pathname.startsWith(`${DASHBOARD_FALLBACK}/`);
    if (parsed.origin !== 'https://portal.local' || !isDashboardPath) return DASHBOARD_FALLBACK;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return DASHBOARD_FALLBACK;
  }
}
