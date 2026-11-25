export const money=(n:number|string)=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(Number(n)||0);
export const moneyExact=(n:number|string)=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(n)||0);
export function creatorReward(orderAmount:number,rate:number,model:'percentage'|'fixed'='percentage'){const raw=model==='percentage'?orderAmount*rate/100:rate;return Math.round((raw+Number.EPSILON)*100)/100;}
