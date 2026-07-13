// 全局配置：只需要填这两项（都不是密钥，可以安全地打进小程序包）
// 注意：Claude API key、微信 AppSecret 等一切密钥只存在于 GitHub Secrets，
// 严禁出现在小程序代码里（小程序包可被反编译）。
module.exports = {
  // 云开发环境 ID（微信开发者工具 → 云开发控制台 → 设置 → 环境ID）
  env: 'your-env-id',
  // data.json 的云存储 fileID：首次运行 GitHub Actions 后从日志里复制，
  // 形如 cloud://your-env-id.xxxx-your-env-id-1234567890/data.json
  // 同路径覆盖上传，fileID 恒定，只需配置一次。
  fileID: 'cloud://your-env-id.xxxx/data.json'
};
