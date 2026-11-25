export const money=(n:number)=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(n);
export function creatorReward(orderAmount:number,rate:number,model:'percentage'|'fixed'='percentage'){const raw=model==='percentage'?orderAmount*rate/100:rate;return Math.round((raw+Number.EPSILON)*100)/100;}
