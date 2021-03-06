from knowledge import settings

import django
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic
from django.utils.translation import ugettext_lazy as _
from django.conf import settings as django_settings
from django.shortcuts import render
from constance import config

from knowledge.managers import QuestionManager, ResponseManager
from knowledge.signals import knowledge_post_save
from django.db.models import Count
from django.core.urlresolvers import reverse
from django.template.loader import render_to_string
from django.core.mail import send_mail
from django.contrib.sites.models import Site

STATUSES = (
    ('public', _('Public')),
    ('private', _('Private')),
    ('internal', _('Internal')),
)


STATUSES_EXTENDED = STATUSES + (
    ('inherit', _('Inherit')),
)

KNOWLEDGE_TYPES = getattr(settings,"KNOWLEDGE_TYPES",False)
if not KNOWLEDGE_TYPES:
    KNOWLEDGE_TYPES = (
        ('challenge', _('Challenge')),
        ('ask', _('Ask')),
        ('tip', _('Tip')),        
    )


class Category(models.Model):
    added = models.DateTimeField(auto_now_add=True)
    lastchanged = models.DateTimeField(auto_now=True)

    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)

    def __unicode__(self):
        return self.title

    class Meta:
        ordering = ['title']
        verbose_name = _('Category')
        verbose_name_plural = _('Categories')


class KnowledgeBase(models.Model):
    """
    The base class for Knowledge models.
    """
    is_question, is_response = False, False

    added = models.DateTimeField(auto_now_add=True)
    lastchanged = models.DateTimeField(auto_now=True)

    user = models.ForeignKey('auth.User' if django.VERSION < (1, 5, 0) else django_settings.AUTH_USER_MODEL, blank=True,
                             null=True, db_index=True)
    alert = models.BooleanField(default=settings.ALERTS,
        verbose_name=_('Tell me when responses are added to my question'),
        help_text=_('Check this if you want to be alerted when a new'
                        ' response is added.'))

    # for anonymous posting, if permitted
    name = models.CharField(max_length=64, blank=True, null=True,
        verbose_name=_('Name'),
        help_text=_('Enter your first and last name.'))
    email = models.EmailField(blank=True, null=True,
        verbose_name=_('Email'),
        help_text=_('Enter a valid email address.'))

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.user and self.name and self.email \
                and not self.id:
            # first time because no id
            self.public(save=False)

        if settings.AUTO_PUBLICIZE and not self.id:
            self.public(save=False)

        super(KnowledgeBase, self).save(*args, **kwargs)

    #########################
    #### GENERIC GETTERS ####
    #########################

    def get_name(self):
        """
        Get local name, then self.user's first/last, and finally
        their username if all else fails.
        """
        name = (self.name or (self.user and (
            u'{0} {1}'.format(self.user.first_name, self.user.last_name).strip()\
            or self.user.username
        )))
        return name.strip() or _("Anonymous")

    get_email = lambda s: s.email or (s.user and s.user.email)
    get_pair = lambda s: (s.get_name(), s.get_email())
    get_user_or_pair = lambda s: s.user or s.get_pair()

    ########################
    #### STATUS METHODS ####
    ########################

    def can_view(self, user):
        """
        Returns a boolean dictating if a User like instance can
        view the current Model instance.
        """

        if self.status == 'inherit' and self.is_response:
            return self.question.can_view(user)

        if self.status == 'internal' and user.is_staff:
            return True

        if self.status == 'private':
            if self.user == user or user.is_staff:
                return True
            if self.is_response and self.question.user == user:
                return True

        if self.status == 'public':
            return True

        return False

    def switch(self, status, save=True):
        self.status = status
        if save:
            self.save()
    switch.alters_data = True

    def public(self, save=True):
        self.switch('public', save)
    public.alters_data = True

    def private(self, save=True):
        self.switch('private', save)
    private.alters_data = True

    def inherit(self, save=True):
        self.switch('inherit', save)
    inherit.alters_data = True

    def internal(self, save=True):
        self.switch('internal', save)
    internal.alters_data = True


class Question(KnowledgeBase):
    is_question = True
    _requesting_user = None

    content_type = models.ForeignKey(ContentType,blank=True, null=True)
    object_id = models.PositiveIntegerField(blank=True, null=True)
    content_object = generic.GenericForeignKey('content_type', 'object_id')

    title = models.CharField(max_length=255,
        verbose_name=_('Question'),
        )
    #help_text=_('Enter your question or suggestion.')
    body = models.TextField(blank=True, null=True,
        verbose_name=_('Description'),
        )
    #help_text=_('Please offer details. Markdown enabled.')

    status = models.CharField(
        verbose_name=_('Status'),
        max_length=32, choices=STATUSES,
        default='public', db_index=True)

    type = models.CharField(
        verbose_name=_('Type'),
        max_length=32, choices=KNOWLEDGE_TYPES,
        default='question', db_index=True)

    locked = models.BooleanField(default=False)

    categories = models.ManyToManyField('knowledge.Category', blank=True)

    redirect = models.CharField(blank=True,null=True,max_length=200)

    objects = QuestionManager()

    class Meta:
        ordering = ['-added']
        verbose_name = _('Question')
        verbose_name_plural = _('Questions')

    def __unicode__(self):
        return self.title

    @models.permalink
    def get_absolute_url(self):
        from django.template.defaultfilters import slugify

        if settings.SLUG_URLS:
            return ('knowledge_thread', [self.id, slugify(self.title)])
        else:
            return ('knowledge_thread_no_slug', [self.id])

    def inherit(self):
        pass

    def internal(self):
        pass

    def lock(self, save=True):
        self.locked = not self.locked
        if save:
            self.save()
    lock.alters_data = True

    ###################
    #### RESPONSES ####
    ###################

    def get_responses(self, user=None):
        user = user or self._requesting_user
        if user:
            return [r for r in self.responses.all().select_related('user') if r.can_view(user)]
        else:
            return self.responses.all().select_related('user')

    def answered(self):
        """
        Returns a boolean indictating whether there any questions.
        """
        return bool(self.get_responses())

    def accepted(self):
        """
        Returns a boolean indictating whether there is a accepted answer
        or not.
        """
        return any([r.accepted for r in self.get_responses()])

    def clear_accepted(self):
        self.get_responses().update(accepted=False)
    clear_accepted.alters_data = True

    def merge(self, response=None):

        session = self.request.session.get('merge_question', False)
        if not session: # not in merge mode, then we're choosing the question to merge with
            self.request.session['merge_question'] = True
            self.request.session['merge_question_pk'] = self.pk
            self.request.session['merge_question_title'] = self.title
        else:

            if self.request.session['merge_question_pk'] == self.pk: return False

            parent_question = Question.objects.get(pk=self.request.session['merge_question_pk'])
            child_question = self

            child_question.redirect = parent_question.get_absolute_url()
            child_question.save()
            
            # move responses over:
            for response in child_question.responses.all():
                response.pk=None
                response.question = parent_question
                response.save()
                

                ## todo: email

            # emails
            site = Site.objects.get_current()
            user = child_question.user
            subject = "Your question: %s" % child_question.title
                        
            context = { 
                "cq" : child_question,
                "pq" : parent_question,
                "user" : user,
                "site" : site,
                "site_name" : getattr(config,"SITE_NAME")
            }
            message = render_to_string('django_knowledge/emails/merge-message.txt', context)
            to = user.email
            frm = getattr(django_settings,'DEFAULT_FROM_EMAIL')
            send_mail(subject, message, frm,
                [to], fail_silently=False)
            
        
    def clear_merge(self):

        try:
            del self.request.session['merge_question']
            del self.request.session['merge_question_pk'] 
            del self.request.session['merge_question_title']
        except KeyError:
            pass

    def accept(self, response=None):
        """
        Given a response, make that the one and only accepted answer.
        Similar to StackOverflow.
        """
        self.clear_accepted()

        if response and response.question == self:
            response.accepted = True
            response.save()
            return True
        else:
            return False
    accept.alters_data = True

    def states(self):
        """
        Handy for checking for mod bar button state.
        """
        return [self.status, 'lock' if self.locked else None]

    ### some filter methods:
    @staticmethod
    def unanswered(resultset):
        """
        Filter a set of responses to only show unanswered
        """
        return resultset.annotate(num_responses=Count('responses')).filter(num_responses=0) #note: this might get heavy on the DB. keeping a list of unanswered ids in redis would be less loady

    @property
    def url(self):
        return self.get_absolute_url()


class Response(KnowledgeBase):
    is_response = True

    question = models.ForeignKey('knowledge.Question',
        related_name='responses')

    body = models.TextField(blank=True, null=True,
        verbose_name=_('Response'),
        help_text=_('Please enter your response. Markdown enabled.'))
    status = models.CharField(
        verbose_name=_('Status'),
        max_length=32, choices=STATUSES_EXTENDED,
        default='inherit', db_index=True)
    accepted = models.BooleanField(default=False)

    objects = ResponseManager()

    class Meta:
        ordering = ['added']
        verbose_name = _('Response')
        verbose_name_plural = _('Responses')

    def __unicode__(self):
        return self.body[0:100] + u'...'

    def states(self):
        """
        Handy for checking for mod bar button state.
        """
        return [self.status, 'accept' if self.accepted else None]

    def accept(self):
        self.question.accept(self)
    accept.alters_data = True


# cannot attach on abstract = True... derp
models.signals.post_save.connect(knowledge_post_save, sender=Question)
models.signals.post_save.connect(knowledge_post_save, sender=Response)
