import type {User} from '../services/api';
export function canAccessPath(user:User,path:string):boolean{
  if(path.startsWith('/admin'))return user.role==='admin';
  if(path==='/brand/referrals')return ['brand','admin'].includes(user.role);
  if(path.startsWith('/brand/'))return user.role==='brand';
  if(['/earnings','/referrals'].includes(path))return user.role==='creator';
  if(path==='/applications')return ['creator','brand','admin'].includes(user.role);
  if(['/creators','/products'].includes(path))return ['brand','admin'].includes(user.role);
  return true;
}
