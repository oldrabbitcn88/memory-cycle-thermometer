// pages/index/index.js —— v3 双向指标展示
const cfg = require('../../config');
const C = { g:'#16a34a', l:'#a3b209', a:'#d97706', r:'#dc2626', b:'#2563eb' };
const colorOf = v => v<30?C.g : v<50?C.l : v<70?C.a : C.r;

Page({
  data:{ loading:true, err:'', d:null, sig:[], topColor:'', botColor:'', tab:'weekly' },
  onLoad(){ this.fetch(); },

  // 开启右上角「转发给好友/群」。缺这个函数，微信会直接禁用转发入口。
  onShareAppMessage(){
    const d = this.data.d;
    return {
      title: d ? `存储周期温度计 · 顶温${d.top}° ${d.phase}` : '存储周期温度计',
      path: '/pages/index/index'
    };
  },
  onPullDownRefresh(){ this.fetch(()=>wx.stopPullDownRefresh()); },

  fetch(done){
    this.setData({loading:true, err:''});
    wx.request({
      url: cfg.dataUrl + '?t=' + Date.now(), method:'GET', dataType:'json',
      success: res=>{
        if(res.statusCode!==200){ this.fail('HTTP '+res.statusCode+'（403多为云存储权限未设为所有用户可读）'); }
        else { this.render(typeof res.data==='string'? JSON.parse(res.data) : res.data); }
        done&&done();
      },
      fail: e=>{ this.fail('请求失败（检查 dataUrl 与 request 合法域名）: '+e.errMsg); done&&done(); }
    });
  },
  fail(msg){ this.setData({loading:false, err:msg}); },

  render(d){
    const sig = (d.signals||[]).map(s=>({
      ...s, color: colorOf(s.score), weightPct: Math.round(s.weight*100),
      metricText: this.fmt(s.id, s.metrics), open:false
    }));
    this.setData({loading:false, d, sig, topColor:colorOf(d.top),
                  botColor: d.bottom>=60? C.g : '#9ca3af'}, ()=>this.draw(d));
  },

  fmt(id, m){
    if(!m) return '';
    if(id===1) return `现货周环比 ${m.wow_pct>0?'+':''}${m.wow_pct}% · 连跌 ${m.weeks_down||0} 周`;
    if(id===2) return `capex同比 ${m.yoy_pct}% · 新fab ${m.new_fabs||0} 座${m.new_entrant?' · 新玩家扩产':''}`;
    if(id===3) return `库存 ${m.weeks} 周${m.lta?' · 长约锁量':''}${m.sellout?' · 售罄话术':''}${m.cancel?' · 已现砍单':''}`;
    if(id===4) return `削减家数 ${m.n_cutting||0}${m.peaked?' · 增速见顶':''}${m.doubt?' · 回报率质疑':''}`;
    if(id===5) return `短缺预测 ${m.years_out} 年 · 看空 ${m.bears||0} 方${m.mega?' · 龙头上市/巨额融资':''}`;
    return '';
  },

  toggle(e){ const i=e.currentTarget.dataset.i; this.setData({['sig['+i+'].open']:!this.data.sig[i].open}); },
  switchTab(e){ this.setData({tab:e.currentTarget.dataset.t}, ()=>this.draw(this.data.d)); },

  draw(d){
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
