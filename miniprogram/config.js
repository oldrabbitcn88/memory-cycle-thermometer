// 全局配置：只有地址，没有密钥（这些是公开下载地址，可以安全地打进小程序包）。
// 注意：Claude API key、腾讯云 SecretId/SecretKey 等一切密钥只存在于 GitHub Secrets，
// 严禁出现在小程序代码里（小程序包可被反编译）。
//
// dataUrls 是「候选地址列表」，按顺序尝试，第一个成功的即采用。
// 这样设计是为了让今后换主机不再需要提审：地址一旦预先写进代码包，
// 启用新主机就只剩后台操作——把域名加进 request 合法域名（该操作不需要审核，
// 每月限 5 次）——代码包一行都不用动。
//
// 列表里每个域名都必须已加入 request 合法域名，否则该项会直接请求失败并降级到下一个。
module.exports = {
  dataUrls: [
    // 主：普通 COS 桶。与云开发套餐计费解耦，按量计费下每年成本约一两毛钱。
    'https://thermometer-1455136845.cos.ap-shanghai.myqcloud.com/data.json',
    // 备：原云开发 Storage。过渡期保留；确认 COS 稳定后可退订云开发个人版套餐，
    //     退订停服后本项会返回 418 并被自动跳过，不需要改代码、不需要再提审。
    'https://636c-cloud1-d0gupqux381b96d12-1455136845.tcb.qcloud.la/data.json'
  ]
};
