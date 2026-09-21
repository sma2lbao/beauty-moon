import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { fetchProducts } from '@/lib/products';

export function ProductsPage() {
  const {
    isPending,
    isError,
    refetch,
    data: products,
  } = useQuery({
    queryKey: ['products'],
    queryFn: fetchProducts,
  });
  const [wishlist, setWishlist] = useState<ReadonlySet<string>>(new Set());

  const toggleWishlist = (id: string) => {
    setWishlist((previous) => {
      const next = new Set(previous);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <section className="mx-auto max-w-5xl px-6 py-16">
      <h1 className="font-display text-3xl">全部产品</h1>
      <p className="mt-3 max-w-md leading-relaxed text-muted-foreground">
        月相系列，按护肤顺序排列。这里目前是演示数据。
      </p>

      {isError ? (
        <div className="mt-12 flex flex-col items-start gap-3 rounded-xl border border-dashed p-8">
          <p className="text-sm">产品列表加载失败，请检查网络后重试。</p>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            重新加载
          </Button>
        </div>
      ) : isPending ? (
        <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((index) => (
            <Skeleton key={index} className="h-64 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {products.map((product) => {
            const saved = wishlist.has(product.id);
            return (
              <Card key={product.id}>
                <CardHeader>
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-display text-lg text-primary">
                      {product.series}系列
                    </span>
                    <span className="text-sm tabular-nums">
                      ¥{product.price}
                    </span>
                  </div>
                  <CardTitle>{product.name}</CardTitle>
                  <CardDescription className="leading-relaxed">
                    {product.description}
                  </CardDescription>
                </CardHeader>
                <CardFooter className="mt-auto">
                  <Button
                    size="sm"
                    variant={saved ? 'default' : 'outline'}
                    onClick={() => toggleWishlist(product.id)}
                    aria-pressed={saved}
                  >
                    {saved ? '已在心愿单' : '加入心愿单'}
                  </Button>
                </CardFooter>
              </Card>
            );
          })}
        </div>
      )}
    </section>
  );
}
