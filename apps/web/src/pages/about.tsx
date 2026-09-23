export function AboutPage() {
  return (
    <section className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="font-display text-3xl">品牌故事</h1>

      <div className="mt-8 space-y-5 leading-relaxed">
        <p>
          美月 Beauty Moon 从一个简单的问题开始：护肤为什么变得这么复杂？
          十几步的流程、看不懂的成分表、每隔几个月就换一套的说法。
        </p>
        <p>
          我们的答案是把节奏交给月亮。月有阴晴圆缺，皮肤也有自己的周期：
          清洁、补水、修护，每个阶段只需要刚好够的那一步。
          月相系列由此而来——从新月的净透，到满月的焕采。
        </p>
        <p>
          我们只做基础护肤这一件事，SKU 砍到最少。货架上没有的，
          是我们判断暂时不需要的。
        </p>
      </div>

      <h2 className="mt-14 font-display text-2xl">我们相信的三件事</h2>
      <dl className="mt-2 divide-y">
        <div className="grid gap-2 py-5 sm:grid-cols-[7rem_1fr]">
          <dt className="font-display text-lg">克制</dt>
          <dd className="text-sm leading-relaxed text-muted-foreground">
            配方表保持能看懂的程度，不加没有必要的原料。
          </dd>
        </div>
        <div className="grid gap-2 py-5 sm:grid-cols-[7rem_1fr]">
          <dt className="font-display text-lg">温和</dt>
          <dd className="text-sm leading-relaxed text-muted-foreground">
            功效不冒进，先保证长期用着舒服，再谈效果。
          </dd>
        </div>
        <div className="grid gap-2 py-5 sm:grid-cols-[7rem_1fr]">
          <dt className="font-display text-lg">诚实</dt>
          <dd className="text-sm leading-relaxed text-muted-foreground">
            做不到的不写，说不清的不讲，文案和成分表保持一致。
          </dd>
        </div>
      </dl>
    </section>
  );
}
