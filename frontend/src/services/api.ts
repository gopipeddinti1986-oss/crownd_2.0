import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

const baseURL=import.meta.env.VITE_API_URL||'/api/v1';
let accessToken:string|null=null;
let refreshInFlight:Promise<AuthPayload|null>|null=null;
type AuthPayload={access_token:string;token_type:'bearer';expires_in:number;user:User};
type RetryConfig=InternalAxiosRequestConfig&{_crowndRetried?:boolean};
export type User={id:number;name:string;email:string;role:'creator'|'brand'|'customer'|'admin'};
export type CommerceProduct={id:number;name:string;slug:string;description:string;category:string;price:string;sale_price:string|null;effective_price:string;discount_percent:number;stock:number;available:boolean;status:string;image_url:string;image_urls:string[];specifications:Record<string,string>;brand:{id:number;name:string;website:string}|null;creator_program?:{campaign:string;reward_model:string;reward_rate:string;active_creators:number}|null;attribution?:{creator_name:string;campaign:string;code:string;attribution_days:number}|null;related_products?:CommerceProduct[]};
export type CartData={items:Array<{id:number;product:CommerceProduct;quantity:number;unit_price:string;line_total:string;available:boolean}>;item_count:number;subtotal:string;shipping:string;total:string;currency:string;unavailable_count:number;attribution:{creator_name:string;campaign:string;code:string;attribution_days:number}|null};
export type CommerceOrder={id:string;order_id:string;amount:string;currency:string;payment_status:string;status:string;created_at:string;updated_at:string;items:Array<{id?:number;product_id:number|null;name:string;brand:string;image_url:string;unit_price:string;quantity:number;line_total:string}>;referral:{creator_name:string;campaign:string;code:string;attribution_days:number}|null;customer?:{name:string;email:string};shipping_address?:{name:string;phone:string;line1:string;line2:string|null;city:string;state:string;postal_code:string;country:string}|null};

// Refresh cookies are HttpOnly and browser-managed. Access tokens live only in this JS module.
export const authApi=axios.create({baseURL,withCredentials:true,headers:{'Content-Type':'application/json'}});
const rawApi=authApi;
export const api=axios.create({baseURL,withCredentials:true,headers:{'Content-Type':'application/json'}});
api.interceptors.request.use(config=>{if(accessToken)config.headers.Authorization=`Bearer ${accessToken}`;return config;});
api.interceptors.response.use(response=>response,async(error:AxiosError)=>{
  const original=error.config as RetryConfig|undefined;
  const url=original?.url||'';
  const isAuthEndpoint=url.startsWith('/auth/')||url.includes('/auth/');
  if(error.response?.status===401&&original&&!original._crowndRetried&&!isAuthEndpoint){
    original._crowndRetried=true;
    try{
      const session=await refreshSession();
      if(session){original.headers.Authorization=`Bearer ${accessToken}`;return api(original);}
    }catch{/* session-expired event clears application auth state */}
    clearAccessToken();
    if(typeof window!=='undefined')window.dispatchEvent(new Event('crownd:session-expired'));
  }
  return Promise.reject(error);
});

export async function refreshSession():Promise<User|null>{
  if(!refreshInFlight){
    refreshInFlight=rawApi.post<AuthPayload>('/auth/refresh',{}).then(({data})=>{
      accessToken=data.access_token;
      return data;
    }).catch(()=>{accessToken=null;return null;}).finally(()=>{refreshInFlight=null;});
  }
  return (await refreshInFlight)?.user||null;
}
export async function login(email:string,password:string):Promise<User>{
  const {data}=await rawApi.post<AuthPayload>('/auth/login',{email,password});
  accessToken=data.access_token;
  return data.user;
}
export async function register(input:Record<string,string>){
  const {data}=await rawApi.post('/auth/register',input);
  return data as {message:string;email_delivery_enabled:boolean};
}
export async function requestVerification(email:string){
  const {data}=await rawApi.post('/auth/email/verification/request',{email});
  return data as {message:string;email_delivery_enabled:boolean};
}
export async function confirmVerification(token:string){
  const {data}=await rawApi.post('/auth/email/verification/confirm',{token});
  return data as {message:string};
}
export async function requestPasswordReset(email:string){
  const {data}=await rawApi.post('/auth/password/reset/request',{email});
  return data as {message:string;email_delivery_enabled:boolean};
}
export async function confirmPasswordReset(token:string,new_password:string){
  const {data}=await rawApi.post('/auth/password/reset/confirm',{token,new_password});
  return data as {message:string};
}
export async function logout(){
  if(!accessToken)await refreshSession();
  if(accessToken)await api.post('/auth/logout');
  clearAccessToken();
}
export function clearAccessToken(){accessToken=null;}
export function getAccessToken(){return accessToken;}
export function setAccessToken(token:string|null){accessToken=token;}
export async function discoverProducts(params:Record<string,unknown>={}){const {data}=await api.get('/products',{params});return data as {items:CommerceProduct[];total:number;page:number;page_size:number;pages:number};}
export async function getProduct(id:number){const {data}=await api.get(`/products/${id}`);return data as CommerceProduct;}
export async function getCart(){const {data}=await api.get('/cart');return data as CartData;}
export async function addCartItem(product_id:number,quantity=1){const {data}=await api.post('/cart/items',{product_id,quantity});return data as CartData;}
export async function updateCartItem(itemId:number,quantity:number){const {data}=await api.patch(`/cart/items/${itemId}`,{quantity});return data as CartData;}
export async function removeCartItem(itemId:number){await api.delete(`/cart/items/${itemId}`);}
export async function clearCart(){await api.delete('/cart');}
export async function checkoutOrder(shipping_address:Record<string,string>,idempotencyKey:string){const {data}=await api.post('/checkout',{shipping_address},{headers:{'Idempotency-Key':idempotencyKey}});return data as CommerceOrder;}
export async function getOrders(page=1){const {data}=await api.get('/orders',{params:{page,page_size:20,view:'customer'}});return data as {items:CommerceOrder[];total:number;page:number;pages:number};}
export async function getOrder(orderId:string){const {data}=await api.get(`/orders/${encodeURIComponent(orderId)}`);return data as CommerceOrder;}
export async function cancelOrder(orderId:string){const {data}=await api.post(`/orders/${encodeURIComponent(orderId)}/cancel`);return data as CommerceOrder;}
export async function trackReferral(code:string){const {data}=await api.get(`/r/${encodeURIComponent(code)}`);return data as {ok:boolean;destination:string;product_id:number|null;attribution_window_days:number};}
export function authErrorMessage(error:unknown,fallback:string){
  const err=error as AxiosError<{detail?:string|{message?:string}}>|undefined;
  const detail=err?.response?.data?.detail;
  return typeof detail==='string'?detail:detail?.message||fallback;
}
