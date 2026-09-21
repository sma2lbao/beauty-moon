import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchProducts } from './products';

afterEach(() => {
  vi.useRealTimers();
});

describe('fetchProducts', () => {
  it('返回月相系列产品列表', async () => {
    vi.useFakeTimers();
    const pending = fetchProducts();
    await vi.advanceTimersByTimeAsync(600);
    const products = await pending;

    expect(products).toHaveLength(6);
  });

  it('每件产品字段完整且 id 唯一', async () => {
    const products = await fetchProducts();
    const ids = new Set(products.map((product) => product.id));

    expect(ids.size).toBe(products.length);
    for (const product of products) {
      expect(product.series).toBeTruthy();
      expect(product.name).toBeTruthy();
      expect(product.description).toBeTruthy();
      expect(product.price).toBeGreaterThan(0);
    }
  });
});
