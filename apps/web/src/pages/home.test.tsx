import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';

import type { Product } from '@/lib/products';
import { fetchProducts } from '@/lib/products';

import { HomePage } from './home';

vi.mock('@/lib/products', () => ({
  fetchProducts: vi.fn(),
}));

const fixtures: Product[] = [
  {
    id: 'new-moon',
    series: '新月',
    name: '净透洁面乳',
    description: '氨基酸配方。',
    price: 89,
  },
  {
    id: 'full-moon',
    series: '满月',
    name: '焕采晚霜',
    description: '夜间修护。',
    price: 219,
  },
];

function renderHome() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('HomePage', () => {
  it('渲染品牌 hero 与行动入口', () => {
    vi.mocked(fetchProducts).mockResolvedValue(fixtures);
    renderHome();

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      '月光落在肌肤上',
    );
    expect(screen.getByRole('link', { name: '看看产品' })).toHaveAttribute(
      'href',
      '/products',
    );
    expect(screen.getByRole('link', { name: '品牌故事' })).toHaveAttribute(
      'href',
      '/about',
    );
  });

  it('数据加载完成后展示系列 teaser 卡片', async () => {
    vi.mocked(fetchProducts).mockResolvedValue(fixtures);
    renderHome();

    expect(await screen.findByText('新月系列')).toBeInTheDocument();
    expect(screen.getByText('净透洁面乳')).toBeInTheDocument();
    expect(screen.getByText('满月系列')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看全部产品' })).toHaveAttribute(
      'href',
      '/products',
    );
  });
});
