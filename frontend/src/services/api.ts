import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

const baseURL=import.meta.env.VITE_API_URL||'/api/v1';
let accessToken:string|null=null;
let refreshInFlight:Promise<AuthPayload|null>|null=null;
type AuthPayload={access_token:string;token_type:'bearer';expires_in:number;user:User};
type RetryConfig=InternalAxiosRequestConfig&{_crowndRetried?:boolean};
export type User={id:number;name:string;email:string;role:'creator'|'brand'|'customer'|'admin'};
export type CommerceProduct={id:number;name:string;slug:string;description:string;category:string;price:string;sale_price:string|null;effective_price:string;discount_percent:number;stock:number;available:boolean;status:string;image_url:string;image_urls:string[];specifications:Record<string,string>;brand:{id:number;name:string;website:string}|null;creator_program?:{campaign:string;reward_model:string;reward_rate:string;active_creators:number}|null;attribution?:{creator_name:string;campaign:string;code:string;attribution_days:number}|null;related_products?:CommerceProduct[]};
export type CartData={items:Array<{id:number;product:CommerceProduct;quantity:number;unit_price:string;line_total:string;available:boolean}>;item_count:number;subtotal:string;shipping:string;total:string;currency:string;unavailable_count:number;attribution:{creator_name:string;campaign:string;code:string;attribution_days:number}|null};
export type PaymentMethod='demo'|'cod'|'online'|'legacy';
export type PaymentAttempt={attempt_number:number;payment_method:PaymentMethod;status:string;amount:string;currency:string;transaction_reference:string|null;notes:string|null;created_at:string;confirmed_at:string|null;confirmed_by:{id:number;name:string;role:string}|null};
export type CommerceOrder={id:string;order_id:string;amount:string;currency:string;payment_method:PaymentMethod;payment_status:string;transaction_reference:string|null;payment_confirmed_at:string|null;payment_confirmed_by:{id:number;name:string;role:string}|null;payment_notes:string|null;payment_attempts:PaymentAttempt[];status:string;created_at:string;updated_at:string;items:Array<{id?:number;product_id:number|null;name:string;brand:string;image_url:string;unit_price:string;quantity:number;line_total:string}>;referral:{creator_name:string;campaign:string;code:string;attribution_days:number}|null;customer?:{name:string;email:string};shipping_address?:{name:string;phone:string;line1:string;line2:string|null;city:string;state:string;postal_code:string;country:string}|null};

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
export async function checkoutOrder(shipping_address:Record<string,string>,payment_method:Exclude<PaymentMethod,'legacy'>,idempotencyKey:string){const {data}=await api.post('/checkout',{shipping_address,payment_method},{headers:{'Idempotency-Key':idempotencyKey}});return data as CommerceOrder;}
export type ReferralLink={id:number;campaign_id:number;campaign:string;creator_id:number;product_id:number|null;code:string;active:boolean;created_at:string;url:string;destination:string;clicks?:number;unique_visitors?:number;product_views?:number;cart_additions?:number;conversions?:Record<string,number>};
export type ReferralConversion={id:number;order_id:string;referral_id:number|null;campaign_id:number|null;creator_id:number|null;status:string;attributed_amount:string;currency:string;is_demo:boolean;payment_method:string;payment_status:string;reason:string|null;created_at:string;confirmed_at:string|null};
export type ReferralMetrics={clicks:number;unique_visitors:number;product_views:number;cart_additions:number;orders:number;confirmed_conversions:number;pending_conversions:number;cancelled_conversions:number;reversed_conversions:number;demo_conversions:number;cod_conversions:number;conversion_rate:number};
export async function createReferralLink(campaign_id:number,product_id?:number){const {data}=await api.post('/referrals/links',{campaign_id,product_id});return data as ReferralLink;}
export async function getReferralLinks(){const {data}=await api.get('/referrals/links');return data as {items:ReferralLink[]};}
export async function getEligibleReferralCampaigns(){const {data}=await api.get('/referrals/eligible-campaigns');return data as Array<{id:number;title:string;product_ids:number[];ends_at:string|null}>;}
export async function getCreatorReferralAnalytics(params:Record<string,number|undefined>={}){const {data}=await api.get('/creator/referral-analytics',{params});return data as {window_days:number;metrics:ReferralMetrics};}
export async function getCreatorConversions(params:Record<string,number|string|undefined>={}){const {data}=await api.get('/creator/conversions',{params});return data as {items:ReferralConversion[];total:number;page:number;pages:number};}
export async function setReferralLinkActive(id:number,active:boolean){const {data}=await api.patch(`/referrals/links/${id}`,{active});return data as ReferralLink;}
export async function getBrandReferralCampaigns(){const {data}=await api.get('/brand/referral-campaigns');return data as Array<{id:number;title:string;status:string;product_ids:number[]}>;}
export async function getBrandCampaignAnalytics(id:number,days=30,product_id?:number){const {data}=await api.get(`/brand/campaign-analytics/${id}`,{params:{days,product_id}});return data;}
export async function getAdminReferralLinks(params:Record<string,string|number|boolean|undefined>={}){const {data}=await api.get('/admin/referrals',{params});return data as {items:ReferralLink[];total:number;page:number;pages:number};}
export async function setAdminReferralLinkActive(id:number,active:boolean){const {data}=await api.patch(`/admin/referrals/links/${id}`,{active});return data;}
export async function getAdminReferralConversions(params:Record<string,string|number|undefined>={}){const {data}=await api.get('/admin/conversions',{params});return data as {items:ReferralConversion[];total:number;page:number;pages:number};}
export async function getAdminReferralRisk(params:Record<string,string|number|undefined>={}){const {data}=await api.get('/admin/referral-risk',{params});return data as {items:Array<{id:number;risk_code:string;referral_id:number|null;conversion_id:number|null;details:string;status:string;created_at:string}>;total:number;page:number;pages:number};}
export async function reviewReferralRisk(id:number,status:'reviewed'|'dismissed',reason:string){const {data}=await api.patch(`/admin/referral-risk/${id}`,{status,reason});return data;}
export async function getAdminOrders(params:Record<string,string|number|undefined>={}){const {data}=await api.get('/admin/orders',{params});return data as {items:CommerceOrder[];total:number;page:number;pages:number};}
export async function getAdminOrder(orderId:string){const {data}=await api.get(`/admin/orders/${encodeURIComponent(orderId)}`);return data as CommerceOrder;}
export async function collectCodPayment(orderId:string){const {data}=await api.post(`/admin/orders/${encodeURIComponent(orderId)}/collect-payment`);return data as CommerceOrder;}
export async function updateAdminOrderStatus(orderId:string,status:string){const {data}=await api.patch(`/orders/${encodeURIComponent(orderId)}/status`,{status});return data as CommerceOrder;}
export async function cancelAdminOrder(orderId:string){const {data}=await api.post(`/admin/orders/${encodeURIComponent(orderId)}/cancel`);return data as CommerceOrder;}
export async function getOrders(page=1){const {data}=await api.get('/orders',{params:{page,page_size:20,view:'customer'}});return data as {items:CommerceOrder[];total:number;page:number;pages:number};}
export async function getOrder(orderId:string){const {data}=await api.get(`/orders/${encodeURIComponent(orderId)}`);return data as CommerceOrder;}
export async function cancelOrder(orderId:string){const {data}=await api.post(`/orders/${encodeURIComponent(orderId)}/cancel`);return data as CommerceOrder;}
export async function trackReferral(code:string){const {data}=await api.get(`/r/${encodeURIComponent(code)}`);return data as {ok:boolean;destination:string;product_id:number|null;attribution_window_days:number};}

export type UserNotification={id:number;category:string;title:string;body:string;action_path:string|null;read_at:string|null;created_at:string};
export type NotificationPage={items:UserNotification[];total:number;unread_count:number;page:number;page_size:number;pages:number};
export type NotificationPreferences={in_app_enabled:boolean;email_enabled:boolean;category_settings:Record<string,{in_app:boolean;email:boolean}>;updated_at:string|null};
export async function getNotifications(page=1,unreadOnly=false){const {data}=await api.get('/notifications',{params:{page,page_size:20,unread_only:unreadOnly}});return data as NotificationPage;}
export async function markNotificationRead(id:number){const {data}=await api.patch(`/notifications/${id}/read`);return data as {id:number;read_at:string};}
export async function markAllNotificationsRead(){const {data}=await api.post('/notifications/read-all');return data as {updated:number};}
export async function getNotificationPreferences(){const {data}=await api.get('/notifications/preferences');return data as NotificationPreferences;}
export async function saveNotificationPreferences(preferences:Omit<NotificationPreferences,'updated_at'>){const {data}=await api.put('/notifications/preferences',preferences);return data as NotificationPreferences;}
export async function getAdminDeliverySummary(){const {data}=await api.get('/admin/notification-deliveries/summary');return data as {counts:Record<string,number>;provider:string;worker_status:string;latest_queued_at:string|null;delivery_semantics:string};}
export async function getAdminDeliveries(params:Record<string,string|number|undefined>={}){const {data}=await api.get('/admin/notification-deliveries',{params});return data as {items:Array<{id:number;category:string;status:string;attempt_count:number;next_attempt_at:string|null;last_error_code:string|null;created_at:string;delivered_at:string|null}>;total:number;page:number;page_size:number;pages:number};}
export type RewardRecord={id:number;order_id:string;creator_id:number;brand_id:number|null;campaign_id:number|null;campaign:string;conversion_id:number|null;product_id:number|null;products:Array<{order_item_id:number|null;product_id:number|null;product_name:string;quantity:number;line_total:string}>;reward_rule_id:number|null;reward_type:string|null;reward_rate:string|null;fixed_amount:string|null;amount:string;eligible_amount:string;excluded_amount:string;currency:string;formula:string|null;rounding_rule:string;calculation_snapshot:Record<string,unknown>;status:string;risk_status:string;is_demo:boolean;payment_method:string;payment_status:string;order_status:string;eligible_at:string|null;created_at:string;updated_at:string|null;payable:boolean;payout_disclosure:string};
export type RewardPage={items:RewardRecord[];total:number;page:number;page_size:number;pages:number;summary?:Record<string,string|number|boolean>};
export type RewardRuleRecord={id:number;campaign_id:number;product_id:number|null;scope_key:string;reward_type:'percentage'|'fixed';rate:string|null;fixed_amount:string|null;currency:string;minimum_eligible_amount:string;max_reward:string|null;max_creator_total:string|null;max_campaign_total:string|null;active:boolean;valid_from:string|null;valid_until:string|null};
export async function getCreatorEarningsSummary(){const {data}=await api.get('/creator/earnings/summary');return data as Record<string,string|number|boolean>;}
export async function getCreatorRewards(params:Record<string,string|number|boolean|undefined>={}){const {data}=await api.get('/creator/rewards',{params});return data as RewardPage;}
export async function getCreatorLedger(params:Record<string,string|number|undefined>={}){const {data}=await api.get('/creator/ledger',{params});return data as {items:Array<{id:number;entry_type:string;amount:string;currency:string;direction:string;reference:string;description:string;created_at:string}>;total:number;page:number;pages:number};}
export async function getBrandRewardAnalytics(params:Record<string,string|number|undefined>={}){const {data}=await api.get('/brand/reward-analytics',{params});return data as {summary:Record<string,string|number|boolean>;campaigns:Array<Record<string,string|number>>;creators:Array<Record<string,string|number>>;customer_data_excluded:boolean};}
export async function getAdminRewards(params:Record<string,string|number|boolean|undefined>={}){const {data}=await api.get('/admin/rewards',{params});return data as RewardPage;}
export async function getAdminRewardHistory(id:number){const {data}=await api.get(`/admin/rewards/${id}/history`);return data as RewardRecord&{ledger_entries:Array<{id:number;entry_type:string;amount:string;direction:string;idempotency_key:string|null;description:string;created_at:string}>;events:Array<{event_type:string;reason:string|null;created_at:string}>;simulated_payouts:Array<{reference:string;amount:string;disclosure:string}>};}
export async function getAdminLedger(params:Record<string,string|number|undefined>={}){const {data}=await api.get('/admin/ledger',{params});return data as {items:Array<{id:number;entry_type:string;amount:string;currency:string;direction:string;reference:string;idempotency_key:string|null;reward_id:number|null;description:string;created_at:string}>;total:number;page:number;pages:number};}
export async function getAdminRewardRules(params:Record<string,string|number|boolean|undefined>={}){const {data}=await api.get('/admin/reward-rules',{params});return data as {items:RewardRuleRecord[];total:number;page:number;pages:number};}
export async function createAdminRewardRule(input:Record<string,unknown>){const {data}=await api.post('/admin/reward-rules',input);return data as RewardRuleRecord;}
export async function updateAdminRewardRule(id:number,input:Record<string,unknown>){const {data}=await api.put(`/admin/reward-rules/${id}`,input);return data as RewardRuleRecord;}
export async function setAdminRewardRuleActive(id:number,active:boolean){const {data}=await api.patch(`/admin/reward-rules/${id}/active`,null,{params:{active}});return data as RewardRuleRecord;}
export async function runAdminRewardAction(id:number,action:'approve'|'reject'|'reverse'|'simulated-payout',reason?:string){const {data}=await api.post(`/admin/rewards/${id}/${action}`,{reason});return data;}
export function authErrorMessage(error:unknown,fallback:string){
  const err=error as AxiosError<{detail?:string|{message?:string}}>|undefined;
  const detail=err?.response?.data?.detail;
  return typeof detail==='string'?detail:detail?.message||fallback;
}

export type CampaignStatus='draft'|'published'|'paused'|'completed'|'cancelled'|'rejected';
export type CampaignRecord={id:number;title:string;slug:string;description:string;category:string;platforms:string;reward_model:'percentage'|'fixed';reward_rate:string;budget:string;status:CampaignStatus;starts_at:string|null;ends_at:string|null;objectives:string[];target_audience:string;creator_requirements:string;visibility:'public'|'unlisted';performance_goals:Record<string,string>;product_ids:number[];products:Array<{id:number;name:string;category:string}>;accepted_creator_count:number;metrics:AnalyticsMetrics;created_at:string};
export type AnalyticsMetrics={orders:number;pending_orders:number;confirmed_orders:number;cancelled_orders:number;reversed_orders:number;simulated_orders:number;cod_orders:number;demo_orders:number;gross_attributed_order_value:string;attributed_revenue:string;confirmed_revenue:string;pending_revenue:string;cancelled_revenue:string;reversed_revenue:string;simulated_revenue:string;clicks:number;unique_visitors:number;product_views:number;cart_additions:number;click_to_order_rate_pct:string;click_to_confirmed_rate_pct:string;conversion_rate_pct:string;visitor_to_order_rate_pct:string;cancellation_rate_pct:string;reversal_rate_pct:string;average_order_value:string;revenue_per_click:string;pending:string;pending_collection:string;under_review:string;eligible:string;approved:string;reversed:string;rejected:string;simulated:string;generated_reward_value:string;reward_records:number;reward_efficiency?:{available:boolean;ratio:string|null;definition:string};roi?:{available:boolean;reason:string;roi_pct:string|null;revenue_to_cost_ratio:string|null;cost_per_conversion:string|null}};
export async function getBrandCampaigns(params:Record<string,string|number|undefined>={}){const {data}=await api.get('/brand/campaigns',{params:{page:1,page_size:100,...params}});return data as {items:CampaignRecord[];total:number;page:number;pages:number};}
export async function getCampaignDetail(id:number){const {data}=await api.get(`/brand/campaigns/${id}`);return data as CampaignRecord;}
export async function createCampaign(input:Record<string,unknown>){const {data}=await api.post('/campaigns',input);return data as {id:number;status:CampaignStatus;slug:string;product_ids:number[]};}
export async function updateCampaign(id:number,input:Record<string,unknown>){const {data}=await api.put(`/campaigns/${id}`,input);return data as CampaignRecord;}
export async function updateCampaignStatus(id:number,status:string){const {data}=await api.patch(`/campaigns/${id}/status`,{status});return data as {id:number;status:CampaignStatus};}
export async function getBrandAnalyticsOverview(params:Record<string,string|number|undefined>={}){const {data}=await api.get('/brand/analytics/overview',{params});return data as {window:{period:string;start:string|null;end_exclusive:string|null;timezone:string};campaigns:{total:number;active:number;completed:number;paused:number;draft:number;by_status:Record<string,number>};creators:{participating:number;generating_confirmed_conversions:number;ranking:string;top_performers:Array<Record<string,any>>};metrics:AnalyticsMetrics;campaign_comparison:Array<{campaign_id:number;campaign:string;status:string;metrics:AnalyticsMetrics}>};}
export async function getCampaignAnalytics(id:number,params:Record<string,string|number|undefined>={}){const {data}=await api.get(`/brand/analytics/campaigns/${id}`,{params});return data as {campaign:CampaignRecord&{name:string;creator_count:number;active_creators:number;budget_ceiling:string};window:{period:string;start:string|null;end_exclusive:string|null};metrics:AnalyticsMetrics&{roi:{available:boolean;reason:string;roi_pct:string|null};reward_efficiency:{available:boolean;ratio:string|null;definition:string};revenue_per_creator:string};creators:Array<Record<string,any>>;products:Array<Record<string,any>>;trends:Array<{date:string;confirmed_orders:number;confirmed_revenue:string;clicks:number}>;funnel:Array<{stage:string;count:number}>;insights:Array<{type:string;subject:string;text:string;rule:string}>};}
export async function getBrandCreatorPerformance(params:Record<string,string|number|undefined>={}){const {data}=await api.get('/brand/analytics/creators',{params});return data as {items:Array<Record<string,any>>;total:number;page:number;pages:number;ranking_criterion:string};}
export async function getBrandProductPerformance(params:Record<string,string|number|undefined>={}){const {data}=await api.get('/brand/analytics/products',{params});return data as {items:Array<Record<string,any>>;total:number;page:number;pages:number};}
export async function downloadBrandAnalyticsCsv(params:Record<string,string|number|undefined>){const {data}=await api.get('/brand/analytics/export',{params,responseType:'blob'});return data as Blob;}
