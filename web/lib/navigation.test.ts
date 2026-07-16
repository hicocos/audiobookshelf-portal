import { describe, expect, it } from 'vitest';
import { getSafeDashboardRedirect } from '@/lib/navigation';

describe('getSafeDashboardRedirect', () => {
  it.each([
    ['/dashboard', '/dashboard'],
    ['/dashboard/library?tab=recent#item', '/dashboard/library?tab=recent#item'],
  ])('allows an internal dashboard destination: %s', (value, expected) => {
    expect(getSafeDashboardRedirect(value)).toBe(expected);
  });

  it.each([
    null,
    '',
    '/',
    '/admin',
    'https://evil.example/dashboard',
    '//evil.example/dashboard',
    '/dashboard.evil.example',
    '/dashboard\\evil.example',
  ])('falls back for an unsafe destination: %s', (value) => {
    expect(getSafeDashboardRedirect(value)).toBe('/dashboard');
  });
});
