import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

const baseURL=import.meta.env.VITE_API_URL||'/api/v1';
let accessToken:string|null=null;
let refreshInFlight:Promise<AuthPayload|null>|null=null;
type AuthPayload={access_token:string;token_type:'bearer';expires_in:number;user:User};
type RetryConfig=InternalAxiosRequestConfig&{_crowndRetried?:boolean};
export type User={id:number;name:string;email:string;role:'creator'|'brand'|'customer'|'admin'};

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
export function authErrorMessage(error:unknown,fallback:string){
  const err=error as AxiosError<{detail?:string|{message?:string}}>|undefined;
  const detail=err?.response?.data?.detail;
  return typeof detail==='string'?detail:detail?.message||fallback;
}
