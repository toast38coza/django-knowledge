from django import forms
from django.utils.translation import ugettext_lazy as _

from knowledge import settings
from knowledge.models import Question, Response, KNOWLEDGE_TYPES

OPTIONAL_FIELDS = ['alert', 'phone_number','body']


__todo__ = """
This is serious badness. Really? Functions masquerading as
clases? Lame. This should be fixed. Sorry.
                                                    ~bryan
"""


def QuestionForm(user, *args, **kwargs):
    """
    Build and return the appropriate form depending
    on the status of the passed in user.
    """

    if user.is_anonymous():
        if not settings.ALLOW_ANONYMOUS:
            return None
        else:
            selected_fields = ['name', 'email', 'title', 'body','content_type','object_id','type','alert']
    else:
        selected_fields = ['user', 'title', 'body', 'status','type','content_type','object_id','alert']

    if settings.ALERTS:
        selected_fields += ['alert']

    class _QuestionForm(forms.ModelForm):
        def __init__(self, *args, **kwargs):
            super(_QuestionForm, self).__init__(*args, **kwargs)

            self.KNOWLEDGE_TYPES = KNOWLEDGE_TYPES
            self.FORM_NAME = 'question'

            for key in self.fields:
                if not key in OPTIONAL_FIELDS:
                    self.fields[key].required = True

            # hide the internal status for non-staff
            qf = self.fields.get('status', None)
            if qf and not user.is_staff:
                choices = list(qf.choices)
                choices.remove(('internal', _('Internal')))
                qf.choices = choices

            # a bit of a hack...
            # hide a field, and use clean to force
            # a specific value of ours
            #'content_type','object_id'
            for key in ['user','content_type','object_id','status','phone_number','type']:
                qf = self.fields.get(key, None)
                if qf:
                    qf.widget = qf.hidden_widget()
                    qf.required = False

            # make the form wider for each input:
            for field in self.fields:
                self.fields[field].widget.attrs['class'] = 'span7'

        # honey pot!
        # phone_number = forms.CharField(required=False)

        def clean_user(self):
            return user

        class Meta:
            model = Question
            fields = selected_fields



    return _QuestionForm(*args, **kwargs)


def ResponseForm(user, question, *args, **kwargs):
    """
    Build and return the appropriate form depending
    on the status of the passed in user and question.
    """

    if question.locked:
        return None

    if not settings.FREE_RESPONSE and not \
            (user.is_staff or question.user == user):
        return None

    if user.is_anonymous():
        if not settings.ALLOW_ANONYMOUS:
            return None
        else:
            selected_fields = ['name', 'email']
    else:
        selected_fields = ['user']

    selected_fields += ['body', 'question']

    if user.is_staff:
        selected_fields += ['status']

    if settings.ALERTS:
        selected_fields += ['alert']

    class _ResponseForm(forms.ModelForm):
        def __init__(self, *args, **kwargs):
            super(_ResponseForm, self).__init__(*args, **kwargs)

            for key in self.fields:
                if not key in OPTIONAL_FIELDS:
                    self.fields[key].required = True

            # a bit of a hack...
            for key in ['user', 'question','status']:
                qf = self.fields.get(key, None)
                if qf:
                    qf.widget = qf.hidden_widget()
                    qf.required = False

            for field in self.fields:
                self.fields[field].widget.attrs['class'] = 'span7'

                self.FORM_NAME = 'response'

        # honey pot!
        # phone_number = forms.CharField(required=False)

        def clean_user(self):
            return user

        def clean_question(self):
            return question

        class Meta:
            model = Response
            fields = selected_fields

    return _ResponseForm(*args, **kwargs)
