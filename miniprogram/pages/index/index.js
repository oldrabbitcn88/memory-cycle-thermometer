// pages/index/index.js —— 温度计首页：读云存储 data.json 并渲染
const cfg = require('../../config');

const COLORS = { green: '#16a34a', lime: '#a3b209', amber: '#d97706', red: '#dc2626' };

function colorOf(v) {
  if (v < 30) return COLORS.green;
  if (v < 50) return COLORS.lime;
  if (v < 70) return COLORS.amber;
  return COLORS.red;
}
function tagOf(v) {
  if (v < 30) return { text: '低温', bg: '#dcfce7', fg: '#166534' };
  if (v < 50) return { text: '温热', bg: '#fef9c3', fg: '#854d0e' };
  if (v < 70) return { text: '偏热', bg: '#ffedd5', fg: '#9a3412' };
  return { text: '高温', bg: '#fee2e2', fg: '#991b1b' };
}

Page({
  data: {
    loading: true,
    err: '',
    d: null,          // 原始 data.json
    sig: [],          // 渲染用信号数组（附加颜色/标签）
    totalColor: '',
    delta: null       // 相对上期的总温度变化
  },

  onLoad() { this.fetch(); },
  onPullDownRefresh() { this.fetch(() => wx.stopPullDownRefresh()); },

  fetch(done) {
    this.setData({ loading: true, err: '' });
    wx.request({
      // 加时间戳绕过 CDN 缓存，确保拿到最新一期
      url: cfg.dataUrl + '?t=' + Date.now(),
      method: 'GET',
      dataType: 'json',
      success: res => {
        if (res.statusCode !== 200) {
          this.fail('HTTP ' + res.statusCode + '（403 多为云存储权限未设为「所有用户可读」）');
        } else {
          const d = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
          this.render(d);
        }
        done && done();
      },
      fail: e => {
        this.fail('请求失败（检查 config.js 的 dataUrl，及该域名是否已加入 request 合法域名）: ' + e.errMsg);
        done && done();
      }
    });
  },

  fail(msg) { this.setData({ loading: false, err: msg }); },

  render(d) {
    const sig = d.signals.map(s => ({
      ...s,
      color: colorOf(s.score),
      tag: tagOf(s.score),
      weightPct: Math.round(s.weight * 100),
      open: false
    }));
    const h = d.history || [];
    const delta = h.length >= 2 ? h[h.length - 1].total - h[h.length - 2].total : null;
    this.setData({ loading: false, d, sig, totalColor: colorOf(d.total), delta }, () => {
      if (h.length >= 2) this.drawChart(h);
    });
  },

  toggle(e) {
    const i = e.currentTarget.dataset.i;
    this.setData({ ['sig[' + i + '].open']: !this.data.sig[i].open });
  },

  copyUrl(e) {
    const url = e.currentTarget.dataset.url;
    wx.setClipboardData({
      data: url,
      success: () => wx.showToast({ title: '链接已复制', icon: 'none' })
    });
  },

  // 历史总温度折线（Canvas 2D）
  drawChart(hist) {
    wx.createSelectorQuery()
      .select('#hist')
      .fields({ node: true, size: true })
      .exec(res => {
        if (!res || !res[0]) return;
        const { node: canvas, width, height } = res[0];
        const dpr = wx.getWindowInfo().pixelRatio || 2;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, width, height);

        const P = { l: 30, r: 12, t: 16, b: 22 };
        const w = width - P.l - P.r, hgt = height - P.t - P.b;
        const y = v => P.t + hgt * (1 - v / 100);
        const x = i => P.l + (hist.length === 1 ? w / 2 : (w * i) / (hist.length - 1));

        // 阈值虚线 50 / 70
        [[50, COLORS.amber], [70, COLORS.red]].forEach(([v, c]) => {
          ctx.strokeStyle = c; ctx.globalAlpha = 0.45;
          ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(P.l, y(v)); ctx.lineTo(width - P.r, y(v)); ctx.stroke();
          ctx.globalAlpha = 1; ctx.setLineDash([]);
          ctx.fillStyle = c; ctx.font = '10px sans-serif';
          ctx.fillText(String(v), 8, y(v) + 3);
        });

        // 折线
        ctx.strokeStyle = '#2563eb'; ctx.lineWidth = 2;
        ctx.beginPath();
        hist.forEach((p, i) => (i === 0 ? ctx.moveTo(x(i), y(p.total)) : ctx.lineTo(x(i), y(p.total))));
        ctx.stroke();

        // 数据点 + 数值 + 日期
        hist.forEach((p, i) => {
          ctx.fillStyle = '#2563eb';
          ctx.beginPath(); ctx.arc(x(i), y(p.total), 3, 0, Math.PI * 2); ctx.fill();
          ctx.fillStyle = '#374151'; ctx.font = '10px sans-serif';
          ctx.fillText(String(p.total), x(i) - 7, y(p.total) - 7);
          if (i === 0 || i === hist.length - 1) {
            ctx.fillStyle = '#9ca3af';
            ctx.fillText(p.date.slice(5), x(i) - 14, height - 6);
          }
        });
      });
  }
});
