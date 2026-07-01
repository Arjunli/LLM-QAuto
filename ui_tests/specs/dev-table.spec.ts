import { test, expect } from '@playwright/test';

test.describe('开发表导航测试', () => {
  test.beforeEach(async ({ page }) => {
    // 1. 导航到带重定向的登录页
    await page.goto('http://192.168.9.202:81/login?redirect=/index');
    
    // 2. 填写登录表单（用户名密码从环境变量获取）
    await page.fill('[name="username"]', process.env.TEST_USERNAME || '');
    await page.fill('[name="password"]', process.env.TEST_PASSWORD || '');
    
    // 3. 提交登录（点击登录按钮，可根据实际调整选择器）
    await page.click('button:has-text("登录")');
    
    // 4. 断言登录成功（跳转到/index或左侧菜单可见）
    await expect(page).toHaveURL(/.*\/index/);
  });

  test('点击左侧开发-开发表后跳转到开发表相关页面', async ({ page }) => {
    // 1. 等待左侧菜单加载完成
    await page.waitForSelector('aside');
    
    // 2. 展开「开发」父菜单（可根据实际调整选择器）
    const devMenu = page.locator('aside :has-text("开发")').first();
    await devMenu.click();
    await devMenu.waitFor();
    
    // 3. 点击「开发表」子菜单
    const devTableMenu = page.locator('aside :has-text("开发表")').first();
    await expect(devTableMenu).toBeVisible();
    await devTableMenu.click();
    
    // 4. 断言页面跳转到开发表相关路径
    await expect(page).toHaveURL(/.*dev.*table/i);
  });
});