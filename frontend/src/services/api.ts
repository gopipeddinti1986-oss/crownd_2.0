import axios from 'axios';
export const api=axios.create({baseURL:import.meta.env.VITE_API_URL||'/api/v1',headers:{'Content-Type':'application/json'}});
api.interceptors.request.use(config=>{const token=localStorage.getItem('crownd_token');if(token)config.headers.Authorization=`Bearer ${token}`;return config;});
export type User={id:number;name:string;email:string;role:'creator'|'brand'|'customer'|'admin'};
export async function login(email:string,password:string){const {data}=await api.post('/auth/login',{email,password});localStorage.setItem('crownd_token',data.access_token);localStorage.setItem('crownd_user',JSON.stringify(data.user));return data.user as User;}
export async function register(input:Record<string,string>){const {data}=await api.post('/auth/register',input);localStorage.setItem('crownd_token',data.access_token);localStorage.setItem('crownd_user',JSON.stringify(data.user));return data.user as User;}
export function logout(){localStorage.removeItem('crownd_token');localStorage.removeItem('crownd_user');}
