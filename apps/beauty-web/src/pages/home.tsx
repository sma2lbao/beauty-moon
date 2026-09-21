import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { fetchProducts } from '@/lib/products';

export function HomePage() {
  const { data: products } = useQuery({
    queryKey: ['products'],
    queryFn: fetchProducts,
  });
  const teaser = products?.slice(0, 3) ?? [];

  return (
    <>
      <section className="mx-auto max-w-5xl px-6 pb-20 pt-16 sm:pt-24">
        <div className="grid items-center gap-12 sm:grid-cols-[1.2fr_1fr]">
          <div className="flex flex-col items-start gap-6">
            <h1 className="font-display text-4xl leading-tight sm:text-5xl">
              月光落在肌肤上，
              <br />
              美得刚刚好。
            </h1>
            <p className="max-w-md leading-relaxed text-muted-foreground">
              美月以月相为序安排护肤：从新月到满月，每个阶段只给皮肤刚好需要的照顾。
              成分克制，配方温和。
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild>
                <Link to="/products">看看产品</Link>
              </Button>
              <Button asChild variant="outline">
                <Link to="/about">品牌故事</Link>
              </Button>
            </div>
          </div>
          <div
            className="moon-disc mx-auto w-44 sm:w-full sm:max-w-xs"
            aria-hidden="true"
          />
        </div>
      </section>

      <section className="border-t">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <div className="flex items-end justify-between gap-4">
            <h2 className="font-display text-2xl">从新月开始</h2>
            <Link
              to="/products"
              className="text-sm text-primary underline-offset-4 hover:underline"
            >
              查看全部产品
            </Link>
          </div>
          <div className="mt-8 grid gap-6 sm:grid-cols-3">
            {teaser.length > 0
              ? teaser.map((product) => (
                  <Card key={product.id}>
                    <CardHeader>
                      <CardTitle className="font-display text-lg">
                        {product.series}系列
                      </CardTitle>
                      <CardDescription>{product.name}</CardDescription>
                    </CardHeader>
                    <CardContent className="text-sm leading-relaxed text-muted-foreground">
                      {product.description}
                    </CardContent>
                  </Card>
                ))
              : [0, 1, 2].map((index) => (
                  <Skeleton key={index} className="h-44 rounded-xl" />
                ))}
          </div>
        </div>
      </section>
    </>
  );
}
