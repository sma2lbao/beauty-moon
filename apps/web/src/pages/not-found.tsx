import { Link } from 'react-router';

import { Button } from '@/components/ui/button';

export function NotFoundPage() {
  return (
    <section className="mx-auto flex max-w-2xl flex-col items-center gap-6 px-6 py-24 text-center">
      <div className="moon-disc w-24" aria-hidden="true" />
      <h1 className="font-display text-3xl">这一页还在夜色里</h1>
      <p className="text-muted-foreground">
        你访问的页面不存在，或者已经搬走了。
      </p>
      <Button asChild>
        <Link to="/">回到首页</Link>
      </Button>
    </section>
  );
}
