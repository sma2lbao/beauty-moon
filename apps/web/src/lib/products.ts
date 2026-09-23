export type Product = {
  id: string;
  /** 月相系列名，例如「新月」「满月」 */
  series: string;
  /** 产品名，例如「净透洁面乳」 */
  name: string;
  description: string;
  /** 人民币，单位：元 */
  price: number;
};

/**
 * Mock 的产品接口。等后端就绪后，把这里换成真实的 fetch，
 * 页面层的 useQuery 不需要改动。
 */
export function fetchProducts(): Promise<Product[]> {
  const products: Product[] = [
    {
      id: 'new-moon',
      series: '新月',
      name: '净透洁面乳',
      description: '氨基酸配方，洗完不紧绷，是早晚护肤的第一步。',
      price: 89,
    },
    {
      id: 'first-quarter',
      series: '弦月',
      name: '水润精华水',
      description: '小分子玻尿酸打底，可以湿敷，敏感肌也友好。',
      price: 139,
    },
    {
      id: 'waxing-gibbous',
      series: '盈月',
      name: '平衡乳液',
      description: '轻乳质地，油皮不闷、干皮够润，一瓶收尾。',
      price: 159,
    },
    {
      id: 'full-moon',
      series: '满月',
      name: '焕采晚霜',
      description: '夜间修护型面霜，第二天起床皮肤透亮。',
      price: 219,
    },
    {
      id: 'hope-moon',
      series: '望月',
      name: '柔雾唇釉',
      description: '豆沙色调，一涂就有气色，成膜后不拔干。',
      price: 99,
    },
    {
      id: 'frost-moon',
      series: '霜月',
      name: '温和卸妆膏',
      description: '卸得干净又不糊眼，乳化快，冲水即净。',
      price: 129,
    },
  ];

  return new Promise((resolve) => {
    setTimeout(() => resolve(products), 600);
  });
}
