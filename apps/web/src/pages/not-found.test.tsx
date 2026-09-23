import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import { NotFoundPage } from './not-found';

function renderPage() {
  return render(
    <MemoryRouter>
      <NotFoundPage />
    </MemoryRouter>,
  );
}

describe('NotFoundPage', () => {
  it('渲染 404 提示与返回首页链接', () => {
    renderPage();

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      '这一页还在夜色里',
    );
    expect(screen.getByRole('link', { name: '回到首页' })).toHaveAttribute(
      'href',
      '/',
    );
  });

  it('渲染月相装饰元素', () => {
    renderPage();
    expect(document.querySelector('.moon-disc')).not.toBeNull();
  });
});
