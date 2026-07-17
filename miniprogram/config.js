// 全局配置：只需要填这一项（公开下载地址，不是密钥，可以安全地打进小程序包）
// 注意：Claude API key、腾讯云 SecretId/SecretKey 等一切密钥只存在于 GitHub Secrets，
// 严禁出现在小程序代码里（小程序包可被反编译）。
module.exports = {
  // data.json 的公开访问地址：首次运行 GitHub Actions 后从日志末尾复制，
  // 形如 https://7878-xxx-4gxxxxxx-1234567890.tcb.qcloud.la/data.json
  // 同路径覆盖上传，地址恒定，只需配置一次。
  // 别忘了把该域名（https://开头到 .la 为止）添加到小程序后台 request 合法域名。
  dataUrl: 'https://your-cdn-domain.tcb.qcloud.la/data.json'
};
