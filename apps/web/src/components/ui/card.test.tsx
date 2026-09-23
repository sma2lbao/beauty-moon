import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from './card';

describe('Card', () => {
  it('渲染各部分的内容', () => {
    render(
      <Card data-testid="card">
        <CardHeader>
          <CardTitle>新月系列</CardTitle>
          <CardDescription>净透洁面乳</CardDescription>
        </CardHeader>
        <CardContent>氨基酸配方</CardContent>
        <CardFooter>¥89</CardFooter>
      </Card>,
    );

    expect(screen.getByTestId('card')).toHaveClass('rounded-xl');
    expect(screen.getByText('新月系列')).toBeInTheDocument();
    expect(screen.getByText('净透洁面乳')).toBeInTheDocument();
    expect(screen.getByText('氨基酸配方')).toBeInTheDocument();
    expect(screen.getByText('¥89')).toBeInTheDocument();
  });

  it('各部分带 data-slot 标记', () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>标题</CardTitle>
          <CardDescription>描述</CardDescription>
        </CardHeader>
        <CardContent>内容</CardContent>
        <CardFooter>底部</CardFooter>
      </Card>,
    );

    expect(document.querySelector('[data-slot="card"]')).not.toBeNull();
    expect(document.querySelector('[data-slot="card-header"]')).not.toBeNull();
    expect(document.querySelector('[data-slot="card-title"]')).not.toBeNull();
    expect(
      document.querySelector('[data-slot="card-description"]'),
    ).not.toBeNull();
    expect(document.querySelector('[data-slot="card-content"]')).not.toBeNull();
    expect(document.querySelector('[data-slot="card-footer"]')).not.toBeNull();
  });
});
