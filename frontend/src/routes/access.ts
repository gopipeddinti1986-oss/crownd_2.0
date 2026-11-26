import type {User} from '../services/api';
export function canAccessPath(user:User,path:string):boolean{
  if(path.startsWith('/admin'))return user.role==='admin';
  if(['/earnings','/referrals'].includes(path))return user.role==='creator';
  if(['/creators','/products','/brand/referrals'].includes(path))return ['brand','admin'].includes(user.role);
  return true;
}
