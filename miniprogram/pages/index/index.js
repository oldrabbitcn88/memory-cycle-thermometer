// pages/index/index.js —— v3 双向指标展示
const cfg = require('../../config');
const C = { g:'#16a34a', l:'#a3b209', a:'#d97706', r:'#dc2626', b:'#2563eb' };
const colorOf = v => v<30?C.g : v<50?C.l : v<70?C.a : C.r;

Page({
  data:{ loading:true, err:'', d:null, sig:[], topColor:'', botColor:'', tab:'weekly',
         tempPct:0, tempOpen:false, botOpen:false, spotTip:'' },
  onLoad(){ this.fetch(); },

  // 开启右上角「转发给好友/群」。缺这个函数，微信会直接禁用转发入口。
  onShareAppMessage(){
    const d = this.data.d;
    return {
      title: d ? `存储周期温度计 · 行业温度${d.top}° ${d.phase}` : '存储周期温度计',
      path: '/pages/index/index'
    };
  },
  onPullDownRefresh(){ this.fetch(()=>wx.stopPullDownRefresh()); },

  // 依次尝试 config.dataUrls 里的候选地址，第一个成功的即采用。
  // 有了降级，换主机时新旧地址可以并存过渡，旧的停服后自动跳过，不必改代码重新提审。
  fetch(done){
    this.setData({loading:true, err:''});
    const urls = cfg.dataUrls && cfg.dataUrls.length ? cfg.dataUrls : [cfg.dataUrl];
    const errs = [];
    const hostOf = u => u.replace(/^https?:\/\//,'').split('/')[0];

    const attempt = i => {
      if(i >= urls.length){
        this.fail('全部数据源均不可用（检查 request 合法域名与存储读权限）:\n' + errs.join('\n'));
        done&&done();
        return;
      }
      wx.request({
        url: urls[i] + '?t=' + Date.now(), method:'GET', dataType:'json', timeout:8000,
        success: res=>{
          if(res.statusCode!==200){
            const hint = res.statusCode===403 ? '（存储权限未设为公有读）'
                       : res.statusCode===418 ? '（云开发环境已停服）' : '';
            errs.push(hostOf(urls[i])+' → HTTP '+res.statusCode+hint);
            attempt(i+1);
            return;
          }
          try {
            this.render(typeof res.data==='string'? JSON.parse(res.data) : res.data);
          } catch(e) {
            errs.push(hostOf(urls[i])+' → 返回内容不是合法 JSON');
            attempt(i+1);
            return;
          }
          done&&done();
        },
        fail: e=>{ errs.push(hostOf(urls[i])+' → '+e.errMsg); attempt(i+1); }
      });
    };
    attempt(0);
  },
  fail(msg){ this.setData({loading:false, err:msg}); },

  render(d){
    const sig = (d.signals||[]).map(s=>({
      ...s, color: colorOf(s.score), weightPct: Math.round(s.weight*100),
      metricText: this.fmt(s.id, s.metrics), open:false
    }));
    // 温度在历史区间中的位置。区间取自 data.json 的 temp_range（回测35期+周度实测），
    // 因为温度的实际取值范围是 21–62 而非 0–100，不标区间读者无从判断高低。
    const tr = d.temp_range || {min:0, max:100};
    const span = Math.max(1, tr.max - tr.min);
    const tempPct = Math.max(0, Math.min(100, (d.top - tr.min) / span * 100));
    this.setData({loading:false, d, sig, tempPct, topColor:colorOf(d.top),
                  botColor: d.bottom>=60? C.g : '#9ca3af'}, ()=>this.draw(d));
  },

  fmt(id, m){
    if(!m) return '';
    // 不写「周环比」：数据源是不定期快照，相邻两点间隔 5~140 天，那个「周」字是假的
    if(id===1) return `现货环比 ${m.wow_pct>0?'+':''}${m.wow_pct}% · 连跌 ${m.weeks_down||0} 期`;
    if(id===2) return `capex同比 ${m.yoy_pct}% · 新fab ${m.new_fabs||0} 座${m.new_entrant?' · 新玩家扩产':''}`;
    if(id===3) return `库存 ${m.weeks} 周${m.lta?' · 长约锁量':''}${m.sellout?' · 售罄话术':''}${m.cancel?' · 已现砍单':''}`;
    if(id===4) return `削减家数 ${m.n_cutting||0}${m.peaked?' · 增速见顶':''}${m.doubt?' · 回报率质疑':''}`;
    if(id===5) return `短缺预期 ${m.years_out} 年 · 异议 ${m.bears||0} 方${m.mega?' · 龙头上市/巨额融资':''}`;
    return '';
  },

  toggleTemp(){ this.setData({tempOpen: !this.data.tempOpen}); },
  toggleBot(){ this.setData({botOpen: !this.data.botOpen}); },

  toggle(e){ const i=e.currentTarget.dataset.i; this.setData({['sig['+i+'].open']:!this.data.sig[i].open}); },
  switchTab(e){ this.setData({tab:e.currentTarget.dataset.t}, ()=>this.draw(this.data.d)); },


  // 现货价走势。数据源发布的是不定期官方快照（相邻两点间隔 5~140 天不等），
  // 因此横轴按序号等距排列而非按真实时间比例——这一点在图下方注明。
  drawSpot(d){
    const src = (d.spot && d.spot.series) || [];
    if(src.length < 2) return;
    wx.createSelectorQuery().select('#sp').fields({node:true,size:true}).exec(res=>{
      if(!res || !res[0]) return;
      const {node:cv, width, height} = res[0];
      const dpr = wx.getWindowInfo().pixelRatio || 2;
      cv.width = width*dpr; cv.height = height*dpr;
      const ctx = cv.getContext('2d'); ctx.scale(dpr,dpr); ctx.clearRect(0,0,width,height);

      const P = {l:34, r:10, t:14, b:20}, w = width-P.l-P.r, h = height-P.t-P.b;
      const vs = src.map(o=>o.p);
      const lo = Math.min.apply(null, vs), hi = Math.max.apply(null, vs);
      const pad = (hi-lo)*0.12 || 1;
      const y0 = lo-pad, y1 = hi+pad;
      const y = v => P.t + h*(1-(v-y0)/(y1-y0));
      const x = i => P.l + w*i/(src.length-1);

      ctx.strokeStyle='#e5e7eb'; ctx.lineWidth=1; ctx.fillStyle='#c9c9c9'; ctx.font='9px sans-serif';
      [y0, (y0+y1)/2, y1].forEach(v=>{
        ctx.beginPath(); ctx.moveTo(P.l, y(v)); ctx.lineTo(width-P.r, y(v)); ctx.stroke();
        ctx.fillText('$'+v.toFixed(0), 4, y(v)+3);
      });

      ctx.strokeStyle = C.b; ctx.lineWidth = 2; ctx.beginPath();
      src.forEach((o,i)=> i ? ctx.lineTo(x(i), y(o.p)) : ctx.moveTo(x(i), y(o.p)));
      ctx.stroke();
      ctx.fillStyle = C.b;
      src.forEach((o,i)=>{ ctx.beginPath(); ctx.arc(x(i), y(o.p), 2.5, 0, 6.284); ctx.fill(); });

      ctx.fillStyle='#9ca3af'; ctx.font='9px sans-serif';
      ctx.fillText(src[0].d.slice(2), P.l-4, height-5);
      ctx.fillText(src[src.length-1].d.slice(2), width-P.r-34, height-5);

      // 存下坐标供触摸取点
      this._sp = src.map((o,i)=>({x:x(i), d:o.d, p:o.p}));
    });
  },

  // 点/滑图上任意位置，显示最近那个数据点的日期与价格。
  // 只有 13 个点、一屏画得下，所以做取点而不是平移——平移在这个点数下是过度设计。
  spotTouch(e){
    const pts = this._sp;
    if(!pts || !pts.length || !e.touches || !e.touches[0]) return;
    const tx = e.touches[0].x;
    let best = pts[0];
    for(const q of pts){ if(Math.abs(q.x-tx) < Math.abs(best.x-tx)) best = q; }
    const i = pts.indexOf(best);
    const prev = i>0 ? pts[i-1] : null;
    const chg = prev ? ((best.p/prev.p-1)*100) : null;
    this.setData({spotTip: best.d + '  $' + best.p.toFixed(2)
      + (chg===null ? '' : '  较上一读数 ' + (chg>0?'+':'') + chg.toFixed(1) + '%')});
  },

  draw(d){
    this.drawSpot(d);
    const src = this.data.tab==='weekly' ? (d.weekly||[]) : (d.quarterly||[]);
    if(src.length<2) return;
    wx.createSelectorQuery().select('#ch').fields({node:true,size:true}).exec(res=>{
      if(!res||!res[0]) return;
      const {node:cv, width, height} = res[0];
      const dpr = wx.getWindowInfo().pixelRatio||2;
      cv.width=width*dpr; cv.height=height*dpr;
      const ctx=cv.getContext('2d'); ctx.scale(dpr,dpr); ctx.clearRect(0,0,width,height);
      const P={l:28,r:10,t:14,b:20}, w=width-P.l-P.r, h=height-P.t-P.b;
      const y=v=>P.t+h*(1-v/100), x=i=>P.l+(src.length===1?w/2:w*i/(src.length-1));
      ctx.strokeStyle='#e5e7eb'; ctx.lineWidth=1;
      [0,50,100].forEach(v=>{ctx.beginPath();ctx.moveTo(P.l,y(v));ctx.lineTo(width-P.r,y(v));ctx.stroke();
        ctx.fillStyle='#c9c9c9';ctx.font='9px sans-serif';ctx.fillText(String(v),6,y(v)+3);});
      const line=(key,col)=>{ ctx.strokeStyle=col; ctx.lineWidth=2; ctx.beginPath();
        src.forEach((p,i)=> i? ctx.lineTo(x(i),y(p[key])) : ctx.moveTo(x(i),y(p[key])) ); ctx.stroke(); };
      line('bottom', C.g); line('top', C.r);
      src.forEach((p,i)=>{ if(p.trig){ ctx.fillStyle=C.r; ctx.beginPath();
        ctx.arc(x(i),y(p.top),3.5,0,6.284); ctx.fill(); }});
      ctx.fillStyle='#9ca3af'; ctx.font='9px sans-serif';
      ctx.fillText(String(src[0].period).slice(2), P.l-4, height-5);
      ctx.fillText(String(src[src.length-1].period).slice(2), width-P.r-32, height-5);
    });
  }
});
