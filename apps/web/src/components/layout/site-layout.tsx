import { Outlet } from 'react-router';

import { SiteFooter } from './site-footer';
import { SiteHeader } from './site-header';

export function SiteLayout() {
  return (
    <div className="flex min-h-svh flex-col bg-background text-foreground">
      <SiteHeader />
      <main className="flex-1">
        <Outlet />
      </main>
      <SiteFooter />
    </div>
  );
}
