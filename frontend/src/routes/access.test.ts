import {describe,expect,it} from 'vitest';
import {canAccessPath} from './access';
const brand={id:1,name:'Brand',email:'brand@example.com',role:'brand' as const};
const creator={id:2,name:'Creator',email:'creator@example.com',role:'creator' as const};
const admin={id:3,name:'Admin',email:'admin@example.com',role:'admin' as const};
describe('role-aware page access',()=>{
 it('limits creator earnings and referrals to creator workspaces',()=>{expect(canAccessPath(brand,'/earnings')).toBe(false);expect(canAccessPath(creator,'/referrals')).toBe(true)});
 it('limits brand discovery/products to brand or admin accounts',()=>{expect(canAccessPath(creator,'/creators')).toBe(false);expect(canAccessPath(brand,'/products')).toBe(true);expect(canAccessPath(admin,'/products')).toBe(true)});
 it('keeps admin pages admin-only',()=>{expect(canAccessPath(brand,'/admin/users')).toBe(false);expect(canAccessPath(creator,'/admin/users')).toBe(false);expect(canAccessPath(admin,'/admin/users')).toBe(true)});
});
