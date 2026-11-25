import {afterEach,describe,expect,it,vi} from 'vitest';
import {AxiosError} from 'axios';
import type {AxiosAdapter} from 'axios';
import {api,authApi,clearAccessToken,getAccessToken,login,refreshSession,setAccessToken} from './api';

const user={id:41,name:'Creator Test',email:'creator@example.com',role:'creator' as const};
const responseAdapter=(payload:unknown,inspect?:(config:any)=>void):AxiosAdapter=>async config=>{
  inspect?.(config);
  return {data:payload,status:200,statusText:'OK',headers:{},config};
};
afterEach(()=>{clearAccessToken();vi.restoreAllMocks();vi.unstubAllGlobals();});
describe('browser authentication token handling',()=>{
  it('keeps the short access token in memory and clears it on sign out',()=>{
    setAccessToken('short-lived-token');
    expect(getAccessToken()).toBe('short-lived-token');
    expect(globalThis.localStorage).toBeUndefined();
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });
  it('keeps a successful login access token in memory only',async()=>{
    authApi.defaults.adapter=responseAdapter({access_token:'login-access-token',token_type:'bearer',expires_in:900,user});
    expect(await login('creator@example.com','never-persist-this-password')).toEqual(user);
    expect(getAccessToken()).toBe('login-access-token');
    expect(globalThis.localStorage).toBeUndefined();
  });
  it('restores a session using the browser-managed cookie and returns user data',async()=>{
    let credentialsIncluded=false;
    authApi.defaults.adapter=responseAdapter({access_token:'new-access-token',token_type:'bearer',expires_in:900,user},config=>{credentialsIncluded=config.withCredentials===true;});
    expect(await refreshSession()).toEqual(user);
    expect(getAccessToken()).toBe('new-access-token');
    expect(credentialsIncluded).toBe(true);
  });
  it('refreshes one protected 401 then retries with the rotated access token',async()=>{
    setAccessToken('expired-access-token');
    authApi.defaults.adapter=responseAdapter({access_token:'rotated-access-token',token_type:'bearer',expires_in:900,user});
    let calls=0;
    api.defaults.adapter=async config=>{
      calls++;
      if(config.headers.Authorization==='Bearer expired-access-token'){
        const response={data:{detail:'expired'},status:401,statusText:'Unauthorized',headers:{},config};
        throw new AxiosError('Unauthorized',AxiosError.ERR_BAD_REQUEST,config,undefined,response);
      }
      return {data:{ok:true},status:200,statusText:'OK',headers:{},config};
    };
    const {data}=await api.get('/analytics/overview');
    expect(data.ok).toBe(true);
    expect(calls).toBe(2);
    expect(getAccessToken()).toBe('rotated-access-token');
  });
  it('clears memory auth and raises session-expired after refresh fails',async()=>{
    setAccessToken('expired-access-token');
    authApi.defaults.adapter=async config=>{const response={data:{detail:'expired'},status:401,statusText:'Unauthorized',headers:{},config};throw new AxiosError('Unauthorized',AxiosError.ERR_BAD_REQUEST,config,undefined,response);};
    api.defaults.adapter=async config=>{const response={data:{detail:'expired'},status:401,statusText:'Unauthorized',headers:{},config};throw new AxiosError('Unauthorized',AxiosError.ERR_BAD_REQUEST,config,undefined,response);};
    const dispatchEvent=vi.fn();vi.stubGlobal('window',{dispatchEvent});
    await expect(api.get('/analytics/overview')).rejects.toBeDefined();
    expect(getAccessToken()).toBeNull();
    expect(dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({type:'crownd:session-expired'}));
  });
  it('does not persist the refresh secret or user snapshot in web storage',()=>{
    setAccessToken('ephemeral');
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });
});
