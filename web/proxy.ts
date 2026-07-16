import { NextRequest, NextResponse } from 'next/server';

const SESSION_COOKIE_NAME = 'moyin_session';
const PROTECTED_ROUTES = ['/dashboard', '/admin/config'];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isProtected = PROTECTED_ROUTES.some((route) => pathname === route || pathname.startsWith(`${route}/`));

  if (!isProtected) return NextResponse.next();

  const hasSession = Boolean(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (hasSession) return NextResponse.next();

  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = pathname.startsWith('/admin') ? '/admin' : '/login';
  loginUrl.searchParams.set('next', pathname || '/dashboard');
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ['/dashboard/:path*', '/admin/config/:path*'],
};
