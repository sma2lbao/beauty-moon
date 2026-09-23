import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Product } from '@/lib/products';
import { fetchProducts } from '@/lib/products';

import { ProductsPage } from './products';

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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ProductsPage />
    </QueryClientProvider>,
  );
}

describe('ProductsPage', () => {
  it('加载中显示骨架屏', () => {
    vi.mocked(fetchProducts).mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      '全部产品',
    );
    expect(document.querySelectorAll('[data-slot="skeleton"]')).toHaveLength(6);
  });

  it('加载完成后渲染产品卡片', async () => {
    vi.mocked(fetchProducts).mockResolvedValue(fixtures);
    renderPage();

    expect(await screen.findByText('净透洁面乳')).toBeInTheDocument();
    expect(screen.getByText('满月系列')).toBeInTheDocument();
    expect(screen.getByText('¥89')).toBeInTheDocument();
    expect(screen.getByText('¥219')).toBeInTheDocument();
  });

  it('心愿单按钮切换状态', async () => {
    vi.mocked(fetchProducts).mockResolvedValue(fixtures);
    renderPage();

    const buttons = await screen.findAllByRole('button', {
      name: '加入心愿单',
    });
    expect(buttons).toHaveLength(2);

    fireEvent.click(buttons[0]);
    expect(buttons[0]).toHaveTextContent('已在心愿单');
    expect(buttons[0]).toHaveAttribute('aria-pressed', 'true');
    expect(buttons[1]).toHaveTextContent('加入心愿单');

    fireEvent.click(buttons[0]);
    expect(buttons[0]).toHaveTextContent('加入心愿单');
    expect(buttons[0]).toHaveAttribute('aria-pressed', 'false');
  });

  it('加载失败显示错误提示，重试后恢复', async () => {
    vi.mocked(fetchProducts).mockRejectedValueOnce(new Error('network down'));
    renderPage();

    expect(
      await screen.findByText('产品列表加载失败，请检查网络后重试。'),
    ).toBeInTheDocument();

    vi.mocked(fetchProducts).mockResolvedValueOnce(fixtures);
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));

    expect(await screen.findByText('净透洁面乳')).toBeInTheDocument();
  });
});
