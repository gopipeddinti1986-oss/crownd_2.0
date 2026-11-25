"""Create local-only sample records. Credentials are deliberately documented demo-only."""
from decimal import Decimal
from sqlalchemy import select
from app.database import Base, engine, SessionLocal
from app.models.entities import User, BrandProfile, CreatorProfile, Product, Campaign, Application, Referral
from app.security import hash_password
Base.metadata.create_all(engine)
db=SessionLocal()
def account(name,email,role,password):
    user=db.scalar(select(User).where(User.email==email))
    if user: return user
    legacy_email={"brand@crownd.example.com":"brand@crownd.local","creator@crownd.example.com":"creator@crownd.local"}.get(email)
    if legacy_email:
        user=db.scalar(select(User).where(User.email==legacy_email))
        if user:
            user.email=email
            db.flush()
            return user
    user=User(name=name,email=email,role=role,password_hash=hash_password(password));db.add(user);db.flush();return user
try:
    brand=account("Noya Botanics","brand@crownd.example.com","brand","CrownDemo!2026")
    creator=account("Jules Lane","creator@crownd.example.com","creator","CrownDemo!2026")
    db.flush()
    if not db.scalar(select(BrandProfile).where(BrandProfile.user_id==brand.id)): db.add(BrandProfile(user_id=brand.id,name="Noya Botanics",industry="Beauty & Wellness",website="https://example.com"))
    if not db.scalar(select(CreatorProfile).where(CreatorProfile.user_id==creator.id)): db.add(CreatorProfile(user_id=creator.id,username="jules.lane",niche="Beauty & Wellness",location="Mumbai, India",bio="Thoughtful skincare and slow mornings.",platform="Instagram",followers=24800,engagement=4.8,crown_score=742,trust_score=93))
    db.flush()
    product=db.scalar(select(Product).where(Product.slug=="everyday-face-oil"))
    if not product:
        product=Product(brand_id=brand.id,name="Everyday Face Oil",slug="everyday-face-oil",description="A lightweight botanical face oil for your softer side.",category="Beauty & Wellness",price=Decimal("3200.00"),stock=75,image_url="",status="active");db.add(product);db.flush()
    campaign=db.scalar(select(Campaign).where(Campaign.slug=="the-everyday-ritual"))
    if not campaign:
        campaign=Campaign(brand_id=brand.id,product_id=product.id,title="The Everyday Ritual",slug="the-everyday-ritual",description="Thoughtful skincare for slower mornings.",category="Beauty & Wellness",platforms="Instagram,YouTube",reward_model="percentage",reward_rate=Decimal("14"),budget=Decimal("125000"),status="published");db.add(campaign);db.flush()
    if not db.scalar(select(Application).where(Application.campaign_id==campaign.id,Application.creator_id==creator.id)):
        db.add(Application(campaign_id=campaign.id,creator_id=creator.id,message="A natural fit with my skincare community.",status="accepted"));db.flush()
    if not db.scalar(select(Referral).where(Referral.campaign_id==campaign.id,Referral.creator_id==creator.id)):
        db.add(Referral(campaign_id=campaign.id,creator_id=creator.id,code="JULES14"))
    db.commit()
    print("Seed ready. Demo only: brand@crownd.example.com / creator@crownd.example.com (password: CrownDemo!2026)")
finally: db.close()
