// app.js
const cfg = require('./config');

App({
  onLaunch() {
    if (!wx.cloud) {
      console.error('基础库版本过低，请在开发者工具中将调试基础库设为 2.2.3 以上');
      return;
    }
    wx.cloud.init({ env: cfg.env, traceUser: false });
  }
});
